-- 공개 누락 finding의 org-<sourceId>는 지출 주체가 아닌 의회 전체를 가리킨다.
-- 원래 scope는 조회·필터에 보존하고 실제 지출 주체에만 참조 무결성을 적용한다.
ALTER TABLE findings DROP CONSTRAINT findings_subject_id_fkey;
ALTER TABLE findings ADD COLUMN spending_subject_id TEXT GENERATED ALWAYS AS (
    CASE
        WHEN data->>'ruleId' = 'DISCLOSURE_GAP'
             AND subject_id = 'org-' || (data->>'sourceId') THEN NULL
        ELSE subject_id
    END
) STORED REFERENCES subjects(id);
