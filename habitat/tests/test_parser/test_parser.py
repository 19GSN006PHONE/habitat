# Copyright 2010, 2011 (C) Adam Greig
#
# This file is part of habitat.
#
# habitat is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# habitat is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with habitat.  If not, see <http://www.gnu.org/licenses/>.

"""
Unit tests for the Parser's Sink class.
"""

import mox
import couchdbkit
from copy import deepcopy
from nose.tools import assert_raises

from ... import parser

class TestParser(object):
    def setup(self):
        self.m = mox.Mox()
        self.mock_module = self.m.CreateMock(parser.ParserModule)
        class MockModule(parser.ParserModule):
            def __new__(cls, parser):
                return self.mock_module
        self.parser_config = {"modules": [
            {"name": "Mock", "class": MockModule}],
            "sensors": [], "certs_dir": "habitat/tests/test_parser/certs",
            "couch_uri": "http://localhost:5984", "couch_db": "test"}
        self.parser = parser.Parser(self.parser_config)

    def teardown(self):
        self.m.UnsetStubs()

    def test_init_doesnt_mess_up_config_modules(self):
        # once upon a time parser didn't deepcopy config, so config['modules']
        # would get all messed up
        assert 'module' not in self.parser_config['modules'][0]

    def test_init_loads_modules_in_config(self):
        assert len(self.parser.modules) == 1
        assert self.parser.modules[0]["module"] == self.mock_module

    def test_init_doesnt_load_bad_modules(self):
        def try_to_load_module(module):
            new_config = deepcopy(self.parser_config) 
            new_config["modules"][0]["class"] = module
            parser.Parser(new_config)

        class EmptyModule(object):
            """A mock parser module without any required methods"""
            pass
        assert_raises(TypeError, try_to_load_module, EmptyModule)

        class NoInitModule(parser.ParserModule):
            """A mock parser module which lacks an __init__ method"""
            __init__ = None
        assert_raises(TypeError, try_to_load_module, NoInitModule)

        class BadInitModule(parser.ParserModule):
            """A mock parser module whose init signature is wrong"""
            def __init__(self):
                pass
        assert_raises(TypeError, try_to_load_module, BadInitModule)

        class NoPreParseModule(parser.ParserModule):
            """A mock parser module with no pre_parse method"""
            pre_parse = None
        assert_raises(TypeError, try_to_load_module, NoPreParseModule)

        class BadPreParseModule(parser.ParserModule):
            """A mock parser module with an incorrect pre_parse signature"""
            def pre_parse(self):
                pass
        assert_raises(TypeError, try_to_load_module, BadPreParseModule)

        class NoParseModule(parser.ParserModule):
            """A mock parser module with no parse method"""
            parse = None
        assert_raises(TypeError, try_to_load_module, NoParseModule)

        class BadParseModule(parser.ParserModule):
            """A mock parser module with an incorrect parse signature"""
            def parse(self):
                pass
        assert_raises(TypeError, try_to_load_module, BadParseModule)

    def test_init_loads_CAs(self):
        assert len(self.parser.certificate_authorities) == 1
        cert = self.parser.certificate_authorities[0]
        assert cert.get_serial_number() == 9315532607032814920L

    def test_init_doesnt_load_non_CA_cert(self):
        config = deepcopy(self.parser_config)
        config['certs_dir'] = 'habitat/tests/test_parser/non_ca_certs'
        assert_raises(ValueError, parser.Parser, config)

    def test_init_connects_to_couch(self):
        self.m.StubOutWithMock(parser, 'couchdbkit')
        s = self.m.CreateMock(couchdbkit.Server)
        parser.couchdbkit.Server("http://localhost:5984").AndReturn(s)
        s.__getitem__("test")
        self.m.ReplayAll()
        parser.Parser(self.parser_config)
        self.m.VerifyAll()

    def test_run_calls_wait(self):
        self.m.StubOutWithMock(parser, 'couchdbkit')
        c = self.m.CreateMock(couchdbkit.Consumer)
        parser.couchdbkit.Consumer(self.parser.db).AndReturn(c)
        c.wait(self.parser._couch_callback, filter="habitat/unparsed", since=0,
                include_docs=True, heartbeat=1000)
        self.m.ReplayAll()
        self.parser.run()
        self.m.VerifyAll()

    def test_couch_callback(self):
        result = {'doc': {'hello': 'world'}, 'seq': 1}
        parsed = {'hello': 'parser'}
        self.m.StubOutWithMock(self.parser, 'parse')
        self.m.StubOutWithMock(self.parser, '_save_updated_doc')
        self.parser.parse(result['doc']).AndReturn(parsed)
        self.parser._save_updated_doc(parsed)
        self.m.ReplayAll()
        self.parser._couch_callback(result)
        self.m.VerifyAll()

    def test_saving_saves(self):
        orig_doc = {"_id": "id", "receivers": [1], 'data': {'a': 1}}
        parsed_doc = deepcopy(orig_doc)
        parsed_doc['data']['b'] = 2
        self.m.StubOutWithMock(self.parser, 'db')
        self.parser.db.__getitem__('id').AndReturn(orig_doc)
        self.parser.db.save_doc(parsed_doc)
        self.m.ReplayAll()
        self.parser._save_updated_doc(parsed_doc)
        self.m.VerifyAll()

    def test_saving_merges(self):
        orig_doc = {"_id": "id", "receivers": [1], 'data': {'a': 1}}
        parsed_doc = deepcopy(orig_doc)
        parsed_doc['data']['b'] = 2
        updated_doc = deepcopy(orig_doc)
        updated_doc['receivers'].append(2)
        merged_doc = deepcopy(parsed_doc)
        merged_doc['receivers'] = deepcopy(updated_doc['receivers'])
        self.m.StubOutWithMock(self.parser, 'db')
        self.parser.db.__getitem__('id').AndReturn(updated_doc)
        self.parser.db.save_doc(merged_doc)
        self.m.ReplayAll()
        self.parser._save_updated_doc(parsed_doc)
        self.m.VerifyAll()
    
    def test_saving_merges_after_conflict(self):
        orig_doc = {"_id": "id", "receivers": [1], 'data': {'a': 1}}
        parsed_doc = deepcopy(orig_doc)
        parsed_doc['data']['b'] = 2
        updated_doc = deepcopy(orig_doc)
        updated_doc['receivers'].append(2)
        merged_doc = deepcopy(parsed_doc)
        merged_doc['receivers'] = deepcopy(updated_doc['receivers'])
        self.m.StubOutWithMock(self.parser, 'db')
        self.parser.db.__getitem__('id').AndReturn(orig_doc)
        self.parser.db.save_doc(parsed_doc).AndRaise(
            couchdbkit.exceptions.ResourceConflict())
        self.parser.db.__getitem__('id').AndReturn(updated_doc)
        self.parser.db.save_doc(merged_doc)
        self.m.ReplayAll()
        self.parser._save_updated_doc(parsed_doc)
        self.m.VerifyAll()
    
    def test_saving_quits_after_many_conflicts(self):
        orig_doc = {"_id": "id", "receivers": [1], 'data': {'a': 1}}
        parsed_doc = deepcopy(orig_doc)
        parsed_doc['data']['b'] = 2
        self.m.StubOutWithMock(self.parser, 'db')
        for i in xrange(30):
            self.parser.db.__getitem__('id').AndReturn(orig_doc)
            self.parser.db.save_doc(parsed_doc).AndRaise(
                couchdbkit.exceptions.ResourceConflict())
        self.m.ReplayAll()
        assert_raises(RuntimeError, self.parser._save_updated_doc, parsed_doc)
        self.m.VerifyAll()

    def test_looks_for_config_doc(self):
        self.m.StubOutWithMock(self.parser, 'db')
        callsign = "habitat"
        time_created = 1234567890
        view_result = {'doc': {'payloads': {callsign: True}}}
        mock_view = self.m.CreateMock(couchdbkit.ViewResults)
        self.parser.db.view("habitat/payload_config", limit=1,
                include_docs=True, startkey=[callsign,
                    time_created]).AndReturn(mock_view)
        mock_view.first().AndReturn(view_result)
        self.m.ReplayAll()
        result = self.parser._find_config_doc(callsign, time_created)
        assert result == view_result['doc']
        self.m.VerifyAll()

    def test_doesnt_use_bad_config_doc(self):
        self.m.StubOutWithMock(self.parser, 'db')
        callsign = "habitat"
        time_created = 1234567890
        view_result = {'doc': {'payloads': {"not habitat": True}}}
        mock_view = self.m.CreateMock(couchdbkit.ViewResults)
        self.parser.db.view("habitat/payload_config", limit=1,
                include_docs=True, startkey=[callsign,
                    time_created]).AndReturn(mock_view)
        mock_view.first().AndReturn(view_result)
        self.m.ReplayAll()
        assert_raises(ValueError, self.parser._find_config_doc, callsign,
                time_created)
        self.m.VerifyAll()
    
    def test_doesnt_parse_if_no_callsign_found(self):
        doc = {'data': {}, 'receivers': {'tester': {}}}
        doc['data']['_raw'] = "dGVzdCBzdHJpbmc="
        doc['receivers']['tester']['time_created'] = 1234567890
        self.mock_module.pre_parse('test string').AndRaise(ValueError)
        self.m.ReplayAll()
        assert self.parser.parse(doc) is None
        self.m.VerifyAll()

    def test_uses_default_config(self):
        doc = {'data': {}, 'receivers': {'tester': {}}}
        doc['data']['_raw'] = "dGVzdCBzdHJpbmc="
        doc['receivers']['tester']['time_created'] = 1234567890
        default = {'sentence': {'protocol': 'Mock'}}
        self.parser.modules[0]['default_config'] = default
        self.mock_module.pre_parse('test string').AndRaise(ValueError)
        self.mock_module.pre_parse('test string').AndReturn('callsign')
        self.mock_module.parse('test string',default['sentence']).AndReturn({})
        self.m.ReplayAll()
        result = self.parser.parse(doc)
        assert result['data']['_parsed']
        assert result['data']['_used_default_config']
        self.m.VerifyAll()

    def test_doesnt_parse_if_no_config(self):
        doc = {'data': {}, 'receivers': {'tester': {}}}
        doc['data']['_raw'] = "dGVzdCBzdHJpbmc="
        doc['receivers']['tester']['time_created'] = 1234567890
        self.m.StubOutWithMock(self.parser, '_find_config_doc')
        self.mock_module.pre_parse('test string').AndReturn('callsign')
        self.parser._find_config_doc('callsign',
                1234567890).AndRaise(ValueError)
        self.m.ReplayAll()
        assert self.parser.parse(doc) is None
        self.m.VerifyAll()

    def test_doesnt_parse_if_bad_config(self):
        doc = {'data': {}, 'receivers': {'tester': {}}}
        doc['data']['_raw'] = "dGVzdCBzdHJpbmc="
        doc['receivers']['tester']['time_created'] = 1234567890
        config = {'payloads': {'callsign': {'messed': 'up'}}, '_id': 'test'}
        self.m.StubOutWithMock(self.parser, '_find_config_doc')
        self.mock_module.pre_parse('test string').AndReturn('callsign')
        self.parser._find_config_doc('callsign', 1234567890).AndReturn(config)
        self.m.ReplayAll()
        assert self.parser.parse(doc) is None
        self.m.VerifyAll()

    def test_doesnt_parse_if_wrong_config_protocol(self):
        doc = {'data': {}, 'receivers': {'tester': {}}}
        doc['data']['_raw'] = "dGVzdCBzdHJpbmc="
        doc['receivers']['tester']['time_created'] = 1234567890
        config = {'payloads': {'callsign': {'sentence': {'protocol': 'Fake'}}}}
        config['_id'] = 'test'
        self.m.StubOutWithMock(self.parser, '_find_config_doc')
        self.mock_module.pre_parse('test string').AndReturn('callsign')
        self.parser._find_config_doc('callsign', 1234567890).AndReturn(config)
        self.m.ReplayAll()
        assert self.parser.parse(doc) is None
        self.m.VerifyAll()

    def test_parses(self):
        doc = {'data': {}, 'receivers': {'tester': {}}}
        doc['data']['_raw'] = "dGVzdCBzdHJpbmc="
        doc['receivers']['tester']['time_created'] = 1234567890
        config = {'payloads': {'callsign': {'sentence': {'protocol': 'Mock'}}}}
        config['_id'] = 'test'
        self.m.StubOutWithMock(self.parser, '_find_config_doc')
        self.mock_module.pre_parse('test string').AndReturn('callsign')
        self.parser._find_config_doc('callsign', 1234567890).AndReturn(config)
        self.mock_module.parse('test string',
                config['payloads']['callsign']['sentence']).AndReturn({})
        self.m.ReplayAll()
        result = self.parser.parse(doc)
        assert result['data']['_parsed']
        assert result['data']['_protocol'] == 'Mock'
        assert result['data']['_flight'] == 'test'
        assert result['data']['_raw'] == "dGVzdCBzdHJpbmc="
        assert result['receivers']['tester']['time_created'] == 1234567890
        assert len(result['receivers']) == 1
        self.m.VerifyAll()

    def setup_parse(self, config=None, doc=None):
        if config is None:
            config = {'payloads': {'callsign': { 'sentence': {}}}}
            config['_id'] = 'test'
            config['payloads']['callsign']['sentence']['protocol'] = 'Mock'
        payload_config = config['payloads']['callsign']['sentence']
        if doc is None:
            doc = {'data': {}, 'receivers': {'tester': {}}}
            doc['data']['_raw'] = "dGVzdCBzdHJpbmc="
            doc['receivers']['tester']['time_created'] = 123
        self.m.StubOutWithMock(self.parser, '_find_config_doc')
        self.mock_module.pre_parse('test string').AndReturn('callsign')
        self.parser._find_config_doc('callsign', 123).AndReturn(config)
        self.mock_module.parse('test string', payload_config).AndReturn({})
        return doc, config

    def test_calls_filters(self):
        doc, config = self.setup_parse()
        self.m.StubOutWithMock(self.parser, '_pre_filter')
        self.m.StubOutWithMock(self.parser, '_intermediate_filter')
        self.m.StubOutWithMock(self.parser, '_post_filter')
        payload_config = config['payloads']['callsign']
        self.parser._pre_filter('test string',
                self.parser.modules[0]).AndReturn('test string')
        self.parser._intermediate_filter('test string',
                payload_config).AndReturn('test string')
        self.parser._post_filter({}, payload_config).AndReturn({})
        self.m.ReplayAll()
        self.parser.parse(doc)
        self.m.VerifyAll()
    
    def test_runs_normal_filters(self):
        pass

    def test_runs_hotfix_filters(self):
        pass

    def test_runs_pre_filters(self):
        self.m.StubOutWithMock(self.parser, '_filter')
        data = 'test data'
        module = {'pre-filters': ['f1', 'f2']}
        self.parser._filter('test data', 'f1').AndReturn('filtered data')
        self.parser._filter('filtered data', 'f2').AndReturn('result')
        self.m.ReplayAll()
        assert self.parser._pre_filter(data, module) == 'result'
        self.m.VerifyAll()

    def test_runs_intermediate_filters(self):
        self.m.StubOutWithMock(self.parser, '_filter')
        data = 'test data'
        config = {'filters': {'intermediate': ['f1', 'f2']}}
        self.parser._filter('test data', 'f1').AndReturn('filtered data')
        self.parser._filter('filtered data', 'f2').AndReturn('result')
        self.m.ReplayAll()
        assert self.parser._intermediate_filter(data, config) == 'result'
        self.m.VerifyAll()

    def test_runs_post_filters(self):
        self.m.StubOutWithMock(self.parser, '_filter')
        data = 'test data'
        config = {'filters': {'post': ['f1', 'f2']}}
        self.parser._filter('test data', 'f1').AndReturn('filtered data')
        self.parser._filter('filtered data', 'f2').AndReturn('result')
        self.m.ReplayAll()
        assert self.parser._post_filter(data, config) == 'result'
        self.m.VerifyAll()

    def test_handles_hotfix_exceptions(self):
        pass

    def test_handles_hotfix_syntax_error(self):
        pass

    def test_hotfix_doesnt_allow_signature_from_other_cert(self):
        pass

    def test_hotfix_doesnt_allow_invalid_signature(self):
        pass

    def test_hotfix_doesnt_allow_missing_signature(self):
        pass

    def test_hotfix_doesnt_allow_missing_certificate(self):
        pass
    
    def test_hotfix_doesnt_allow_missing_code(self):
        pass

    def test_hotfix_doesnt_allow_certs_not_signed_by_ca(self):
        pass

    def test_hotfix_doesnt_allow_unloadable_certs(self):
        pass

    def test_hotfix_doesnt_allow_certs_with_paths_in_name(self):
        pass
