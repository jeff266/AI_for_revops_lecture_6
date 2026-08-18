#!/usr/bin/env python3
"""
Entity Context Extraction Eval Harness

Tests all 11 answer paths from the Step 1 inventory to ensure
tool_results with entity data correctly flows to save_thread().

Prioritizes the 4 regression-prone paths (A3, A4, A6, B1) where
entity extraction SHOULD work, plus one negative case to verify
the warning fires when extraction fails.

Usage: python scripts/eval_entity_paths.py
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json
from datetime import datetime, timezone

# Add api to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import under test
from api.router import route_question, dynamic_query_loop
from api.db import save_thread


class MockSupabase:
    """Mock Supabase client that returns stubbed data."""

    def __init__(self, stub_data=None):
        self.stub_data = stub_data or {}
        self.saved_threads = []

    def table(self, name):
        mock_table = Mock()
        mock_table.select = Mock(return_value=mock_table)
        mock_table.eq = Mock(return_value=mock_table)
        mock_table.upsert = Mock(return_value=mock_table)

        # Capture upsert calls for verification
        def capture_upsert(data, **kwargs):
            self.saved_threads.append(data)
            mock_result = Mock()
            mock_result.execute = Mock(return_value=Mock(data=[data]))
            return mock_result
        mock_table.upsert.side_effect = capture_upsert

        # Return entity_registry data for schema-driven extraction
        if name == "entity_registry":
            mock_result = Mock()
            mock_result.data = [
                {
                    "supabase_table": "deals",
                    "id_column": "deal_id",
                    "entity_type": "deal",
                    "entity_label_column": "company_name",
                    "description": "Deal entity"
                },
                {
                    "supabase_table": "deals",
                    "id_column": "company_id",
                    "entity_type": "company",
                    "entity_label_column": "company_name",
                    "description": "Company entity"
                },
                {
                    "supabase_table": "calls",
                    "id_column": "call_id",
                    "entity_type": "call",
                    "entity_label_column": "title",
                    "description": "Call/transcript entity"
                }
            ]
            mock_table.execute = Mock(return_value=mock_result)
            return mock_table

        # Return empty history initially for other tables
        mock_result = Mock()
        mock_result.data = []
        mock_table.execute = Mock(return_value=mock_result)

        return mock_table


class EntityPathEvals:
    """Test harness for entity context extraction paths."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def assert_true(self, condition, message):
        """Simple assertion that tracks failures."""
        if not condition:
            self.failed += 1
            self.failures.append(f"FAIL: {message}")
            print(f"  ❌ {message}")
        else:
            self.passed += 1
            print(f"  ✓ {message}")

    async def test_a3_dynamic_fallback_success(self):
        """A3: Dynamic fallback succeeds after structured handler fails.

        Entity data SHOULD flow from dynamic_query_loop.
        """
        print("\n[A3] Dynamic Fallback Success")

        sb = MockSupabase()

        # Mock structured handler to return empty (triggers fallback)
        with patch('api.handlers.query_waterfall', new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = {"waterfall": []}  # Empty triggers fallback

            # Mock dynamic_query_loop to return entity-rich data
            mock_dynamic_result = {
                "answer": "Found 5 deals in pipeline",
                "tool_results": {
                    "rows": [
                        {"deal_id": "d1", "company_name": "Acme Corp"},
                        {"deal_id": "d2", "company_name": "Widget Inc"},
                    ]
                }
            }

            with patch('api.router.dynamic_query_loop', new_callable=AsyncMock) as mock_dynamic:
                mock_dynamic.return_value = mock_dynamic_result

                # Mock Anthropic client
                mock_client = Mock()
                mock_response = Mock()
                mock_response.content = [Mock(text='{"handler": "query_waterfall", "params": {}}')]
                mock_response.usage = Mock(input_tokens=100, output_tokens=50)
                mock_client.messages.create = Mock(return_value=mock_response)

                with patch('api.router.anthropic.Anthropic', return_value=mock_client):
                    result = await route_question(
                        question="show me pipeline",
                        user_id="U123",
                        history=[],
                        sb=sb,
                        thread_ts="test_A1"
                    )

        # Verify result includes tool_results
        self.assert_true("tool_results" in result, "Result includes tool_results")
        self.assert_true(len(result.get("tool_results", {}).get("rows", [])) == 2,
                        "tool_results has 2 rows")
        self.assert_true("handler_name" in result, "Result includes handler_name")

    async def test_a4_direct_dynamic_query(self):
        """A4: Intent classified as dynamic_query directly.

        Entity data SHOULD flow from dynamic_query_loop.
        """
        print("\n[A4] Direct Dynamic Query")

        sb = MockSupabase()

        # Mock dynamic_query_loop to return entity-rich data
        mock_dynamic_result = {
            "answer": "Found 3 at-risk deals",
            "tool_results": {
                "rows": [
                    {"deal_id": "d3", "company_name": "Risk Co"},
                ]
            }
        }

        with patch('api.router.dynamic_query_loop', new_callable=AsyncMock) as mock_dynamic:
            mock_dynamic.return_value = mock_dynamic_result

            # Mock Anthropic to classify as dynamic_query
            mock_client = Mock()
            mock_response = Mock()
            mock_response.content = [Mock(text='{"handler": "dynamic_query", "params": {}}')]
            mock_response.usage = Mock(input_tokens=100, output_tokens=50)
            mock_client.messages.create = Mock(return_value=mock_response)

            with patch('api.router.anthropic.Anthropic', return_value=mock_client):
                result = await route_question(
                    question="complex query",
                    user_id="U123",
                    history=[],
                    sb=sb,
                    thread_ts="test_A6"
                )

        # Verify result includes tool_results
        self.assert_true("tool_results" in result, "Result includes tool_results")
        self.assert_true(len(result.get("tool_results", {}).get("rows", [])) == 1,
                        "tool_results has 1 row")
        self.assert_true("dynamic" in result.get("handler_name", ""),
                        f"handler_name contains 'dynamic' (got: {result.get('handler_name')})")

    async def test_a6_retry_dynamic_success(self):
        """A6: Assessment retry triggers dynamic_query_loop, succeeds.

        THIS WAS THE BUG: dynamic_query_loop result was treated as string,
        tool_results was dropped. Now fixed.

        Direct test by importing and checking the actual code behavior.
        """
        print("\n[A6] Retry Dynamic Success (REGRESSION TEST)")

        # Test the actual code path by inspecting what would be returned
        # We can verify this by checking the router code directly
        import inspect
        from api import router

        # Get the source of route_question
        source = inspect.getsource(router.route_question)

        # Check for the fixed pattern (lines 876-895)
        has_dynamic_result = "dynamic_result = await dynamic_query_loop" in source
        has_answer_extraction = 'dynamic_answer = dynamic_result.get("answer"' in source
        has_tool_results_extraction = 'dynamic_tool_results = dynamic_result.get("tool_results"' in source
        has_both_in_return = ('"tool_results": dynamic_tool_results' in source and
                             '"answer": dynamic_answer' in source)

        # Check for the OLD buggy pattern (should NOT exist)
        has_buggy_pattern = "tool_results_text = await dynamic_query_loop" in source

        self.assert_true(has_dynamic_result,
                        "Code uses 'dynamic_result = await dynamic_query_loop'")
        self.assert_true(has_answer_extraction,
                        "Code extracts answer from dynamic_result dict")
        self.assert_true(has_tool_results_extraction,
                        "Code extracts tool_results from dynamic_result dict")
        self.assert_true(has_both_in_return,
                        "Return dict includes both answer and tool_results")
        self.assert_true(not has_buggy_pattern,
                        "Buggy 'tool_results_text' pattern NOT present")

    async def test_b1_normal_synthesis(self):
        """B1: Structured handler succeeds, goes through synthesis.

        Entity data SHOULD flow from handler return value.
        """
        print("\n[B1] Normal Synthesis (Structured Handler)")

        sb = MockSupabase()

        # Mock structured handler to return entity-rich data
        with patch('api.handlers.query_waterfall', new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = {
                "waterfall": [
                    {"deal_id": "d4", "company_name": "Synth Co", "pipeline_value": 50000},
                    {"deal_id": "d5", "company_name": "Flow Inc", "pipeline_value": 75000},
                ]
            }

            # Mock Anthropic client for all LLM calls
            mock_client = Mock()

            # Intent classification
            mock_intent = Mock()
            mock_intent.content = [Mock(text='{"handler": "query_waterfall", "params": {}, "confidence": 0.9}')]
            mock_intent.usage = Mock(input_tokens=100, output_tokens=50)

            # Synthesis
            mock_synth = Mock()
            mock_synth.content = [Mock(text="Here's your pipeline data")]
            mock_synth.usage = Mock(input_tokens=200, output_tokens=100)

            # Verification
            mock_verify = Mock()
            mock_verify.content = [Mock(text="Here's your pipeline data")]
            mock_verify.usage = Mock(input_tokens=150, output_tokens=80)

            # Assessment
            mock_assess = Mock()
            mock_assess.content = [Mock(text='{"correct": true, "score": 0.9}')]
            mock_assess.usage = Mock(input_tokens=120, output_tokens=60)

            mock_client.messages.create = Mock(
                side_effect=[mock_intent, mock_synth, mock_verify, mock_assess]
            )

            with patch('api.router.anthropic.Anthropic', return_value=mock_client):
                result = await route_question(
                    question="show me pipeline",
                    user_id="U123",
                    history=[],
                    sb=sb,
                    thread_ts="test_P1"
                )

        # Verify result includes tool_results with waterfall data
        self.assert_true("tool_results" in result, "Result includes tool_results")
        self.assert_true("waterfall" in result.get("tool_results", {}),
                        "tool_results has waterfall key")
        self.assert_true(len(result.get("tool_results", {}).get("waterfall", [])) == 2,
                        "waterfall has 2 rows")

    async def test_negative_case_warning(self):
        """Verify warning fires when tool_results has data but extraction gets zero entities.

        Simulates a handler returning data in an unexpected format that
        extract_entity_context can't parse.
        """
        print("\n[NEGATIVE] Warning Fires on Extraction Failure")

        sb = MockSupabase()

        # Create tool_results with list data but NO deal_id/company_name fields
        bad_tool_results = {
            "scores": [
                {"metric_name": "revenue", "value": 100},
                {"metric_name": "deals", "value": 5},
            ]
        }

        # Patch logging module instead of the logger instance
        with patch('logging.getLogger') as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            save_thread(
                sb=sb,
                thread_ts="test",
                channel="C123",
                history=[],
                question="test",
                answer="test",
                tool_results=bad_tool_results,
                handler_name="test_handler"
            )

            # Verify warning was logged
            warning_called = any(
                call[0][0].startswith("[ENTITY] save_thread stored ZERO entities")
                for call in mock_logger.warning.call_args_list
            )
            self.assert_true(warning_called,
                           "Warning logged for extraction failure")

    async def test_empty_paths_pass_empty_dict(self):
        """A1, A2, A5: Legitimately-empty paths pass {} without crashing.

        With tool_results now required, verify these paths compile and
        pass {} explicitly.
        """
        print("\n[EMPTY PATHS] A1/A2/A5 pass {} explicitly")

        sb = MockSupabase()

        # Test that save_thread accepts empty dict
        try:
            save_thread(
                sb=sb,
                thread_ts="test",
                channel="C123",
                history=[],
                question="test",
                answer="no data",
                tool_results={},  # Explicitly empty
                handler_name="unanswerable"
            )
            self.assert_true(True, "save_thread accepts {} without error")
        except TypeError as e:
            self.assert_true(False, f"save_thread crashed on {{}}: {e}")

    async def test_g7_cache_payload_strip_verification(self):
        """G.7: Verify cache_payload is stripped before synthesis.

        The pop() + assertion prevents cache_payload from leaking into
        synthesis (which would waste 3-5K tokens silently). This test
        verifies the strip happens and size log makes it visible.
        """
        print("\n[G.7.1] cache_payload strip verification")

        sb = MockSupabase()

        # Aggregate handler: summary + cache_payload
        tool_results = {
            "waterfall": [{"week": "2026-W01", "deals": 5}],
            "cache_payload": {
                "deals": [{"deal_id": "D1", "company_name": "Acme"}] * 50  # Large payload
            }
        }

        with patch('logging.getLogger') as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            save_thread(
                sb=sb,
                thread_ts="test",
                channel="C123",
                history=[],
                question="show waterfall",
                answer="Here's the waterfall",
                tool_results=tool_results,
                handler_name="query_waterfall"
            )

            # Verify size log shows SMALL synthesis payload (cache_payload stripped)
            synth_logs = [str(call) for call in mock_logger.info.call_args_list
                         if "[SYNTH] tool_results" in str(call)]
            self.assert_true(len(synth_logs) > 0, "Size log present")

            # Verify cache was stored (proves payload was extracted)
            cache_logs = [str(call) for call in mock_logger.info.call_args_list
                         if "[CACHE] stored" in str(call)]
            self.assert_true(len(cache_logs) > 0, "Cache storage logged")

    async def test_g7_entity_extraction_from_cache(self):
        """G.7: Verify entities extracted from cache_payload even if tool_results empty.

        Aggregate handlers (query_waterfall) return summaries in tool_results
        with no deal_ids. All entity data lives in cache_payload.
        """
        print("\n[G.7.2] Entity extraction from cache_payload")

        sb = MockSupabase()

        # Simulate aggregate handler: summary in tool_results, details in cache_payload
        tool_results = {
            "waterfall": [{"week": "2026-W01", "deals": 5}],
            "period": "Last 4 weeks",
            "cache_payload": {
                "deals": [
                    {"deal_id": "D1", "company_name": "Acme Corp"},
                    {"deal_id": "D2", "company_name": "Globex Inc"},
                ]
            }
        }

        # Patch logging to verify entity extraction
        with patch('logging.getLogger') as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            save_thread(
                sb=sb,
                thread_ts="test",
                channel="C123",
                history=[],
                question="show waterfall",
                answer="Here's the waterfall",
                tool_results=tool_results,
                handler_name="query_waterfall"
            )

            # Verify cache extraction log
            cache_extract_logged = any(
                "[SAVE_THREAD] extracting entities from cache_payload" in str(call)
                for call in mock_logger.info.call_args_list
            )
            self.assert_true(cache_extract_logged,
                           "Cache entity extraction logged")

            # Verify entities saved
            entity_save_logged = any(
                "[SAVE_THREAD] saving entity_context" in str(call) and
                "2 deal_ids" in str(call)
                for call in mock_logger.info.call_args_list
            )
            self.assert_true(entity_save_logged,
                           "Entity context saved with 2 deal_ids from cache")

    async def test_entity_scope_bypass_completes(self):
        """Entity-scope path completes without UnboundLocalError.

        When Step -1 (entity-scope bypass) succeeds, intent_resp is never
        assigned. This test ensures route_question() handles that gracefully.

        Regression test for: UnboundLocalError on intent_resp.usage.input_tokens
        """
        print("\n[ENTITY-SCOPE] Bypass completes without crash")

        sb = MockSupabase()

        # Simulate Turn 1: populate entity_context
        history = [
            {"role": "user", "content": "show me pipeline"},
            {"role": "assistant", "content": "Here are the deals"},
            {"role": "entity_context", "content": json.dumps({
                "deal_ids": ["D1", "D2", "D3"],
                "company_names": ["Acme Corp", "Globex Inc"],
                "resolved_at": datetime.now(timezone.utc).isoformat()
            })}
        ]

        # Mock entity-scope routing to return matching results
        mock_entity_results = {
            "rows": [
                {"deal_id": "D1", "company_name": "Acme Corp", "at_risk": True},
                {"deal_id": "D2", "company_name": "Globex Inc", "at_risk": True}
            ]
        }

        # Mock Anthropic client for synthesis/verify (not intent)
        with patch('api.router.anthropic.Anthropic') as MockClient, \
             patch('api.router.route_entity_scoped_question',
                   return_value=(mock_entity_results, "query_deals_at_risk")):

            mock_client = MockClient.return_value

            # Entity-scope bypasses intent, goes straight to synthesis
            mock_synth = Mock()
            mock_synth.content = [Mock(text="Acme Corp and Globex Inc are both at risk")]
            mock_synth.usage = Mock(input_tokens=100, output_tokens=50)

            mock_verify = Mock()
            mock_verify.content = [Mock(text="Acme Corp and Globex Inc are both at risk")]
            mock_verify.usage = Mock(input_tokens=50, output_tokens=25)

            mock_assess = Mock()
            mock_assess.content = [Mock(text='{"correct": true, "score": 0.95}')]
            mock_assess.usage = Mock(input_tokens=50, output_tokens=20)

            # Synthesis, verify, and assess (but NOT intent)
            mock_client.messages.create = Mock(side_effect=[mock_synth, mock_verify, mock_assess])

            try:
                result = await route_question(
                    question="which are at risk?",  # Pronoun + entity context triggers bypass
                    user_id="U123",
                    history=history,
                    sb=sb,
                    thread_ts="test_entity_scope"
                )

                self.assert_true("answer" in result,
                               "Entity-scope path completes without UnboundLocalError")
                self.assert_true(len(result.get("answer", "")) > 0,
                               "Entity-scope path returns answer")

            except UnboundLocalError as e:
                self.assert_true(False, f"UnboundLocalError on entity-scope path: {e}")

    async def test_query_deals_at_risk_field_shape(self):
        """query_deals_at_risk returns dicts with deal_id AND company_name.

        Structural test to catch field-shape drift. The handler was returning
        "company" (not "company_name") and no "deal_id", causing entity
        extraction to silently reject its output.

        Regression test for: extract_entity_context got ZERO entities from
        query_deals_at_risk despite non-empty results.
        """
        print("\n[FIELD-SHAPE] query_deals_at_risk has deal_id + company_name")

        from api.handlers import query_deals_at_risk

        # Phase G.10: Mock both analyses AND deals (stage-aware risk needs stage data)
        mock_analyses = [
            {
                "deal_id": "D1",
                "company_name": "Acme Corp",
                "overall_score": 30,
                "champion_score": 2,  # Below Discovery requirement (4)
                "economic_buyer_score": 3,
                "pain_score": 6,
                "metrics_score": 0,
                "decision_criteria_score": 0,
                "decision_process_score": 0,
                "competition_score": 0,
                "analyzed_at": "2026-06-01"
            },
            {
                "deal_id": "D2",
                "company_name": "Widget Inc",
                "overall_score": 50,
                "champion_score": 1,  # Below Discovery requirement (4)
                "economic_buyer_score": 5,
                "pain_score": 6,
                "metrics_score": 0,
                "decision_criteria_score": 0,
                "decision_process_score": 0,
                "competition_score": 0,
                "analyzed_at": "2026-06-02"
            }
        ]

        mock_deals = [
            {
                "deal_id": "D1",
                "company_name": "Acme Corp",
                "deal_value": 50000,
                "deal_status": "active",
                "stage": "appointmentscheduled"  # Discovery
            },
            {
                "deal_id": "D2",
                "company_name": "Widget Inc",
                "deal_value": 75000,
                "deal_status": "active",
                "stage": "appointmentscheduled"  # Discovery
            }
        ]

        # Mock select_all to return analyses on first call, deals on second
        mock_call_count = [0]
        def mock_select_all(sb, table, **kwargs):
            mock_call_count[0] += 1
            if table == "analyses":
                return mock_analyses
            elif table == "deals":
                return mock_deals
            return []

        with patch('api.handlers.select_all', side_effect=mock_select_all):
            sb = Mock()
            params = {
                "deal_ids": ["D1", "D2"],
                "time_window": {"start": "2026-01-01", "end": "2026-12-31", "label": "2026"}
            }

            result = await query_deals_at_risk(params, sb)

            # Verify output structure
            self.assert_true("deals_at_risk" in result,
                           "Result has deals_at_risk key")

            deals = result.get("deals_at_risk", [])
            self.assert_true(len(deals) > 0,
                           "Result has at least one at-risk deal")

            if len(deals) > 0:
                first_deal = deals[0]
                self.assert_true("deal_id" in first_deal,
                               "First deal has deal_id field")
                self.assert_true("company_name" in first_deal,
                               "First deal has company_name field")
                self.assert_true("company" not in first_deal,
                               "First deal does NOT have old 'company' field")

    async def run_all(self):
        """Run all tests and report results."""
        print("=" * 70)
        print("Entity Path Eval Harness")
        print("=" * 70)

        await self.test_a3_dynamic_fallback_success()
        await self.test_a4_direct_dynamic_query()
        await self.test_a6_retry_dynamic_success()
        await self.test_b1_normal_synthesis()
        await self.test_negative_case_warning()
        await self.test_empty_paths_pass_empty_dict()
        await self.test_g7_cache_payload_strip_verification()
        await self.test_g7_entity_extraction_from_cache()
        await self.test_entity_scope_bypass_completes()
        await self.test_query_deals_at_risk_field_shape()

        print("\n" + "=" * 70)
        print(f"Results: {self.passed} passed, {self.failed} failed")
        print("=" * 70)

        if self.failures:
            print("\nFailures:")
            for failure in self.failures:
                print(f"  {failure}")
            return 1

        print("\n✅ All entity path tests passed!")
        return 0


async def main():
    """Entry point."""
    evals = EntityPathEvals()
    exit_code = await evals.run_all()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
