# F1/F2 RED evidence — 2026-09-12

Production baseline: `7a4a0a8daf5f3ec6aa0111cfc08e1e14e87cae05`, branch `deploy/railway-stage-b`.
All RED runs below preceded edits to `app/services/generation_contracts.py` and `app/static/app.js`. Tests and synthetic fixtures were added first.

## Corrected API/service RED run

Command:

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_f1_f2_rereview_fixes.py
```

Exit 1. Each of the three exact rereview fixtures independently failed at API generation, API GET, API idempotent replay, service GET, and service idempotent replay. Generation/replay returned 201, GET returned 200, and direct service calls did not raise. These are assertion failures against actual services and SQLite, not setup errors.

```text
FFFFFF                                                          [100%]
================================== FAILURES ===================================
_ test_serialized_private_values_rejected_by_api_generation[json_authorization] _
tests\test_f1_f2_rereview_fixes.py:26: in test_serialized_private_values_rejected_by_api_generation
    assert response.status_code == 503
E   assert 201 == 503
E    +  where 201 = <Response [201 Created]>.status_code
___ test_serialized_private_values_rejected_by_api_generation[provider_raw] ___
tests\test_f1_f2_rereview_fixes.py:26: in test_serialized_private_values_rejected_by_api_generation
    assert response.status_code == 503
E   assert 201 == 503
E    +  where 201 = <Response [201 Created]>.status_code
_ test_serialized_private_values_rejected_by_api_generation[message_envelope] _
tests\test_f1_f2_rereview_fixes.py:26: in test_serialized_private_values_rejected_by_api_generation
    assert response.status_code == 503
E   assert 201 == 503
E    +  where 201 = <Response [201 Created]>.status_code
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_get-json_authorization] _
tests\test_f1_f2_rereview_fixes.py:46: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    assert response.status_code == 503
E   assert 200 == 503
E    +  where 200 = <Response [200 OK]>.status_code
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_get-provider_raw] _
tests\test_f1_f2_rereview_fixes.py:46: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    assert response.status_code == 503
E   assert 200 == 503
E    +  where 200 = <Response [200 OK]>.status_code
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_get-message_envelope] _
tests\test_f1_f2_rereview_fixes.py:46: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    assert response.status_code == 503
E   assert 200 == 503
E    +  where 200 = <Response [200 OK]>.status_code
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_replay-json_authorization] _
tests\test_f1_f2_rereview_fixes.py:46: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    assert response.status_code == 503
E   assert 201 == 503
E    +  where 201 = <Response [201 Created]>.status_code
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_replay-provider_raw] _
tests\test_f1_f2_rereview_fixes.py:46: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    assert response.status_code == 503
E   assert 201 == 503
E    +  where 201 = <Response [201 Created]>.status_code
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_replay-message_envelope] _
tests\test_f1_f2_rereview_fixes.py:46: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    assert response.status_code == 503
E   assert 201 == 503
E    +  where 201 = <Response [201 Created]>.status_code
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_get-json_authorization] _
tests\test_f1_f2_rereview_fixes.py:50: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_get-provider_raw] _
tests\test_f1_f2_rereview_fixes.py:50: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_get-message_envelope] _
tests\test_f1_f2_rereview_fixes.py:50: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_replay-json_authorization] _
tests\test_f1_f2_rereview_fixes.py:50: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_replay-provider_raw] _
tests\test_f1_f2_rereview_fixes.py:50: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_replay-message_envelope] _
tests\test_f1_f2_rereview_fixes.py:50: in test_serialized_private_values_in_legacy_storage_fail_get_and_replay
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
=========================== short test summary info ===========================
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_rejected_by_api_generation[json_authorization]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_rejected_by_api_generation[provider_raw]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_rejected_by_api_generation[message_envelope]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_get-json_authorization]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_get-provider_raw]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_get-message_envelope]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_replay-json_authorization]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_replay-provider_raw]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[api_replay-message_envelope]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_get-json_authorization]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_get-provider_raw]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_get-message_envelope]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_replay-json_authorization]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_replay-provider_raw]
FAILED tests/test_f1_f2_rereview_fixes.py::test_serialized_private_values_in_legacy_storage_fail_get_and_replay[service_replay-message_envelope]
15 failed in 14.14s
EXTERNAL_CONNECTION_ATTEMPTS=0
```

## Shared generation validator RED run

Command:

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_f1_f2_rereview_fixes.py tests/test_whole_branch_fixes.py::test_reference_raw_values_rejected_before_persistence tests/test_whole_branch_fixes.py::test_allowed_value_positions_reject_raw_material tests/test_whole_branch_fixes.py::test_partial_reference_generation_load_and_retry_preserve_ordinary_prose
```

Initial run: 30 failed, 88 passed in 41.76s; external connection attempts 0. Of those failures, 24 are genuine generation-value regressions: three strings in three reference fields and five guidance/solution/document positions. The remaining six were early API tests; they are superseded by the corrected isolated run above and are not added to the genuine-RED count.

The initial API generation setup lacked a participant and hit a SQLite NOT NULL error; the initial combined storage test eagerly issued an unnecessary fresh-generation request because it supplied the idempotency key as a header. Before production edits, tests were corrected to set participant `test`, pass the key in the JSON body, and parameterize every boundary independently. An intermediate 15-case run still had three participant-related setup failures. Only the final 15-assertion-failure run above is used as API RED proof.

Verbatim generation failure excerpt from the initial run:

```text
_ test_reference_raw_values_rejected_before_persistence[possible_target_users-{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[possible_target_users-{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[possible_target_users-{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[uncertainty_notice-{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[uncertainty_notice-{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[uncertainty_notice-{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[fixture_disclosure-{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[fixture_disclosure-{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_reference_raw_values_rejected_before_persistence[fixture_disclosure-{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}] _
tests\test_whole_branch_fixes.py:37: in test_reference_raw_values_rejected_before_persistence
    with pytest.raises(StructuredOutputContractError) as caught:
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}-guidance_scalar] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}-guidance_list] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}-guidance_disclosure] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}-solution] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}-document] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}-guidance_scalar] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}-guidance_list] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}-guidance_disclosure] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}-solution] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}-document] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}-guidance_scalar] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}-guidance_list] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}-guidance_disclosure] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}-solution] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
_ test_allowed_value_positions_reject_raw_material[{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}-document] _
tests\test_whole_branch_fixes.py:80: in test_allowed_value_positions_reject_raw_material
    with pytest.raises(StructuredOutputContractError):
E   Failed: DID NOT RAISE StructuredOutputContractError
```

## Actual frontend adapter/editor RED run

Command: `node tests/whole_branch_fix_harness.js`

Exit 1, `SUMMARY passed=152 failed=50`. Markers 10/11/12 correspond to json_authorization/provider_raw/message_envelope. Thirty failures cover eight adapter/value positions plus reference renderer and document editor for each string. Twenty failures cover the new negative wording and positive completion commitments in version/draft adapters and editors. Existing controls, including ordinary JSON/prose and selected identity/pages, passed.

The harness loads the actual app.js into its existing behavior-only fake DOM; this is not browser/layout acceptance and does not assess R5.

```text
PASS R1 toAIReferenceViewModel marker 0
PASS R1 toAIReferenceViewModel marker 0
PASS R1 toAIReferenceViewModel marker 0
PASS R1 toEvidenceGuidanceViewModel marker 0
PASS R1 toEvidenceGuidanceViewModel marker 0
PASS R1 toEvidenceGuidanceViewModel marker 0
PASS R1 toSolutionsViewModel marker 0
PASS R1 toDocumentWorkspaceViewModel marker 0
PASS R1 renderer excludes marker 0
PASS R1 document editor excludes marker 0
PASS R1 toAIReferenceViewModel marker 1
PASS R1 toAIReferenceViewModel marker 1
PASS R1 toAIReferenceViewModel marker 1
PASS R1 toEvidenceGuidanceViewModel marker 1
PASS R1 toEvidenceGuidanceViewModel marker 1
PASS R1 toEvidenceGuidanceViewModel marker 1
PASS R1 toSolutionsViewModel marker 1
PASS R1 toDocumentWorkspaceViewModel marker 1
PASS R1 renderer excludes marker 1
PASS R1 document editor excludes marker 1
PASS R1 toAIReferenceViewModel marker 2
PASS R1 toAIReferenceViewModel marker 2
PASS R1 toAIReferenceViewModel marker 2
PASS R1 toEvidenceGuidanceViewModel marker 2
PASS R1 toEvidenceGuidanceViewModel marker 2
PASS R1 toEvidenceGuidanceViewModel marker 2
PASS R1 toSolutionsViewModel marker 2
PASS R1 toDocumentWorkspaceViewModel marker 2
PASS R1 renderer excludes marker 2
PASS R1 document editor excludes marker 2
PASS R1 toAIReferenceViewModel marker 3
PASS R1 toAIReferenceViewModel marker 3
PASS R1 toAIReferenceViewModel marker 3
PASS R1 toEvidenceGuidanceViewModel marker 3
PASS R1 toEvidenceGuidanceViewModel marker 3
PASS R1 toEvidenceGuidanceViewModel marker 3
PASS R1 toSolutionsViewModel marker 3
PASS R1 toDocumentWorkspaceViewModel marker 3
PASS R1 renderer excludes marker 3
PASS R1 document editor excludes marker 3
PASS R1 toAIReferenceViewModel marker 4
PASS R1 toAIReferenceViewModel marker 4
PASS R1 toAIReferenceViewModel marker 4
PASS R1 toEvidenceGuidanceViewModel marker 4
PASS R1 toEvidenceGuidanceViewModel marker 4
PASS R1 toEvidenceGuidanceViewModel marker 4
PASS R1 toSolutionsViewModel marker 4
PASS R1 toDocumentWorkspaceViewModel marker 4
PASS R1 renderer excludes marker 4
PASS R1 document editor excludes marker 4
PASS R1 toAIReferenceViewModel marker 5
PASS R1 toAIReferenceViewModel marker 5
PASS R1 toAIReferenceViewModel marker 5
PASS R1 toEvidenceGuidanceViewModel marker 5
PASS R1 toEvidenceGuidanceViewModel marker 5
PASS R1 toEvidenceGuidanceViewModel marker 5
PASS R1 toSolutionsViewModel marker 5
PASS R1 toDocumentWorkspaceViewModel marker 5
PASS R1 renderer excludes marker 5
PASS R1 document editor excludes marker 5
PASS R1 toAIReferenceViewModel marker 6
PASS R1 toAIReferenceViewModel marker 6
PASS R1 toAIReferenceViewModel marker 6
PASS R1 toEvidenceGuidanceViewModel marker 6
PASS R1 toEvidenceGuidanceViewModel marker 6
PASS R1 toEvidenceGuidanceViewModel marker 6
PASS R1 toSolutionsViewModel marker 6
PASS R1 toDocumentWorkspaceViewModel marker 6
PASS R1 renderer excludes marker 6
PASS R1 document editor excludes marker 6
PASS R1 toAIReferenceViewModel marker 7
PASS R1 toAIReferenceViewModel marker 7
PASS R1 toAIReferenceViewModel marker 7
PASS R1 toEvidenceGuidanceViewModel marker 7
PASS R1 toEvidenceGuidanceViewModel marker 7
PASS R1 toEvidenceGuidanceViewModel marker 7
PASS R1 toSolutionsViewModel marker 7
PASS R1 toDocumentWorkspaceViewModel marker 7
PASS R1 renderer excludes marker 7
PASS R1 document editor excludes marker 7
PASS R1 toAIReferenceViewModel marker 8
PASS R1 toAIReferenceViewModel marker 8
PASS R1 toAIReferenceViewModel marker 8
PASS R1 toEvidenceGuidanceViewModel marker 8
PASS R1 toEvidenceGuidanceViewModel marker 8
PASS R1 toEvidenceGuidanceViewModel marker 8
PASS R1 toSolutionsViewModel marker 8
PASS R1 toDocumentWorkspaceViewModel marker 8
PASS R1 renderer excludes marker 8
PASS R1 document editor excludes marker 8
PASS R1 toAIReferenceViewModel marker 9
PASS R1 toAIReferenceViewModel marker 9
PASS R1 toAIReferenceViewModel marker 9
PASS R1 toEvidenceGuidanceViewModel marker 9
PASS R1 toEvidenceGuidanceViewModel marker 9
PASS R1 toEvidenceGuidanceViewModel marker 9
PASS R1 toSolutionsViewModel marker 9
PASS R1 toDocumentWorkspaceViewModel marker 9
PASS R1 renderer excludes marker 9
PASS R1 document editor excludes marker 9
FAIL R1 toAIReferenceViewModel marker 10: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 10: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 10: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 10: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 10: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 10: Expected values to be strictly equal:
FAIL R1 toSolutionsViewModel marker 10: Expected values to be strictly equal:
FAIL R1 toDocumentWorkspaceViewModel marker 10: Expected values to be strictly equal:
FAIL R1 renderer excludes marker 10: The expression evaluated to a falsy value:
FAIL R1 document editor excludes marker 10: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 11: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 11: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 11: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 11: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 11: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 11: Expected values to be strictly equal:
FAIL R1 toSolutionsViewModel marker 11: Expected values to be strictly equal:
FAIL R1 toDocumentWorkspaceViewModel marker 11: Expected values to be strictly equal:
FAIL R1 renderer excludes marker 11: The expression evaluated to a falsy value:
FAIL R1 document editor excludes marker 11: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 12: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 12: Expected values to be strictly equal:
FAIL R1 toAIReferenceViewModel marker 12: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 12: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 12: Expected values to be strictly equal:
FAIL R1 toEvidenceGuidanceViewModel marker 12: Expected values to be strictly equal:
FAIL R1 toSolutionsViewModel marker 12: Expected values to be strictly equal:
FAIL R1 toDocumentWorkspaceViewModel marker 12: Expected values to be strictly equal:
FAIL R1 renderer excludes marker 12: The expression evaluated to a falsy value:
FAIL R1 document editor excludes marker 12: Expected values to be strictly equal:
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R1 ordinary prose preserved
PASS R1 ordinary JSON/prose survives all other adapters
PASS R2 partial reference generate, persisted load, retry
PASS R2 empty references rejected
PASS R2 Action Card who_or_where stays mandatory
PASS R2 Action Card action_steps stays mandatory
PASS R2 Action Card acceptable_artifacts stays mandatory
PASS R2 Action Card fill_template stays mandatory
PASS R4 honest exclusion 明确不做支付。
PASS R4 honest exclusion 本版本不包含支付和广告。
PASS R4 honest exclusion ## 非目标
- 支付
- 广告
PASS R4 honest exclusion ## Non-goals
- 支付
PASS R4 honest exclusion We will not implement 支付.
PASS R4 honest exclusion 支付不在本期范围内。
PASS R4 honest exclusion 不做广告，但不支持支付。
PASS R4 actual scope drift 增加支付功能。
PASS R4 actual scope drift 不做广告，但支持支付。
PASS R4 actual scope drift 明确不做支付。
实现支付结算。
PASS R4 actual scope drift ## 非目标
- 支付
## 功能
- 支持支付
PASS R4 actual scope drift ## 非目标
- 支付
### 实现方案
- 支持支付
PASS R4 actual scope drift We will implement 支付.
PASS R4 actual scope drift 不做广告，支付功能需要实现。
PASS R4 actual scope drift 支付不在本期范围内，但现在增加支付。
PASS R4 actual scope drift ## 非目标
- 支持支付功能
PASS R4 selected identity and pages remain required
PASS R4 non-goal heading cannot conceal a positive commitment
FAIL F2 version: honest future exclusion: Expected values to be strictly equal:
FAIL F2 version editor: honest future exclusion: Expected values to be strictly equal:
FAIL F2 draft: honest future exclusion: Expected values to be strictly equal:
FAIL F2 draft editor: honest future exclusion: Expected values to be strictly equal:
FAIL F2 version: honest integration exclusion: Expected values to be strictly equal:
FAIL F2 version editor: honest integration exclusion: Expected values to be strictly equal:
FAIL F2 draft: honest integration exclusion: Expected values to be strictly equal:
FAIL F2 draft editor: honest integration exclusion: Expected values to be strictly equal:
FAIL F2 version: negative under non-goal heading: Expected values to be strictly equal:
FAIL F2 version editor: negative under non-goal heading: Expected values to be strictly equal:
FAIL F2 draft: negative under non-goal heading: Expected values to be strictly equal:
FAIL F2 draft editor: negative under non-goal heading: Expected values to be strictly equal:
FAIL F2 version: positive completion under non-goal heading: Expected values to be strictly equal:
FAIL F2 version editor: positive completion under non-goal heading: Expected values to be strictly equal:
FAIL F2 draft: positive completion under non-goal heading: Expected values to be strictly equal:
FAIL F2 draft editor: positive completion under non-goal heading: Expected values to be strictly equal:
FAIL F2 version: positive commitment in heading: Expected values to be strictly equal:
FAIL F2 version editor: positive commitment in heading: Expected values to be strictly equal:
FAIL F2 draft: positive commitment in heading: Expected values to be strictly equal:
FAIL F2 draft editor: positive commitment in heading: Expected values to be strictly equal:
PASS F2 version: positive support control
PASS F2 version editor: positive support control
PASS F2 draft: positive support control
PASS F2 draft editor: positive support control
PASS F2 version: negative followed by positive
PASS F2 version editor: negative followed by positive
PASS F2 draft: negative followed by positive
PASS F2 draft editor: negative followed by positive
PASS F2 version: positive after negative in non-goals
PASS F2 version editor: positive after negative in non-goals
PASS F2 draft: positive after negative in non-goals
PASS F2 draft editor: positive after negative in non-goals
SUMMARY passed=152 failed=50
```
