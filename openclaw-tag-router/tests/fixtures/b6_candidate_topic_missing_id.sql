\set ON_ERROR_STOP on

UPDATE media_product.decision_traces
   SET canonical_data = canonical_data - '创作运行ID'
 WHERE public_id = 'trace_01_001';
