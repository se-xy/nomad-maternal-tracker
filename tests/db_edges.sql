BEGIN;
UPDATE system_clock SET mode='simulation',simulated_at='2026-11-01T00:00:00Z';
SELECT ingest_batch('{"d":"NMT-001","via":"cell","pts":[["2026-11-01T00:00:00Z",3,38,50,30]]}');
SELECT ingest_batch('{"d":"NMT-001","via":"cell","pts":[["2026-11-01T00:00:00Z",3,38,50,30]]}');
DO $$ BEGIN
 IF (SELECT count(*) FROM positions WHERE device_id='NMT-001')<>1 THEN RAISE EXCEPTION 'Dedup failed'; END IF;
 BEGIN
 PERFORM ingest_batch('{"d":"NMT-001","via":"cell","pts":[["2026-11-01T01:00:00Z",999,38,50,30]]}');
 RAISE EXCEPTION 'Invalid latitude accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
END $$;
SELECT advance_simulation_clock('2026-11-01T13:00:00Z');
DO $$ BEGIN
 IF NOT (SELECT lost FROM latest_status WHERE device_id='NMT-001') THEN RAISE EXCEPTION 'Clock outage failed'; END IF;
END $$;
SELECT enqueue_alerts();
SELECT enqueue_alerts();
DO $$ DECLARE m notification_outbox; BEGIN
 IF (SELECT count(*) FROM notification_outbox WHERE alert_type='LOST_CONTACT')<>1 THEN RAISE EXCEPTION 'Outbox dedup failed'; END IF;
 SELECT * INTO m FROM claim_notifications() LIMIT 1;
 IF m.id IS NULL THEN RAISE EXCEPTION 'Claim failed'; END IF;
 IF acknowledge_notification(m.id,'wrong') THEN RAISE EXCEPTION 'Invalid lease accepted'; END IF;
 IF NOT acknowledge_notification(m.id,m.lease_token) THEN RAISE EXCEPTION 'Acknowledgement failed'; END IF;
END $$;
ROLLBACK;
