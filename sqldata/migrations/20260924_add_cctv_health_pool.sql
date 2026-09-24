CREATE TABLE IF NOT EXISTS cctv_health (
    cctv_id INT UNSIGNED NOT NULL,
    is_usable TINYINT(1) NOT NULL,
    quality_score DECIMAL(5, 2) DEFAULT NULL,
    checked_at DATETIME(6) NOT NULL,
    failure_reason VARCHAR(255) DEFAULT NULL,
    PRIMARY KEY (cctv_id),
    KEY cctv_health_usable_checked (is_usable, checked_at, quality_score),
    CONSTRAINT cctv_health_cctv_fk
        FOREIGN KEY (cctv_id) REFERENCES cctv (ID) ON DELETE CASCADE,
    CONSTRAINT cctv_health_usable_check
        CHECK (is_usable IN (0, 1)),
    CONSTRAINT cctv_health_quality_check
        CHECK (quality_score IS NULL OR quality_score BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
