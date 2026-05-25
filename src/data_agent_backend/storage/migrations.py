MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            project_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            thread_id TEXT,
            project_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            thread_id TEXT,
            project_id TEXT,
            type TEXT NOT NULL,
            uri TEXT NOT NULL,
            local_path TEXT,
            content_hash TEXT,
            created_at TEXT NOT NULL,
            created_by_tool TEXT NOT NULL,
            created_by_node TEXT,
            parent_ids_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            permissions_json TEXT,
            approval_id TEXT,
            policy_decision_id TEXT
        );

        CREATE TABLE IF NOT EXISTS artifact_previews (
            artifact_id TEXT PRIMARY KEY,
            preview_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id)
        );

        CREATE TABLE IF NOT EXISTS artifact_lineage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id TEXT NOT NULL,
            child_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS claim_evidence (
            claim_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            PRIMARY KEY (claim_id, artifact_id)
        );

        CREATE TABLE IF NOT EXISTS memory_records (
            memory_id TEXT PRIMARY KEY,
            namespace_json TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL,
            content_text TEXT NOT NULL,
            content_json TEXT,
            source_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            approval_id TEXT,
            risk_flags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            requested_by TEXT,
            decided_by TEXT,
            edited_payload_json TEXT,
            reason TEXT,
            run_id TEXT,
            thread_id TEXT,
            project_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS approval_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            approval_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            actor TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS policy_audit_logs (
            decision_id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            allowed INTEGER NOT NULL,
            requires_approval INTEGER NOT NULL,
            risk_level TEXT NOT NULL,
            reason TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS exports (
            export_id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            format TEXT NOT NULL,
            destination TEXT,
            output_path TEXT,
            approval_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        ALTER TABLE runs ADD COLUMN status TEXT NOT NULL DEFAULT 'created';

        CREATE TABLE IF NOT EXISTS run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            node_name TEXT,
            tool_name TEXT,
            artifact_ids_json TEXT NOT NULL DEFAULT '[]',
            approval_id TEXT,
            memory_ids_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS datasources (
            datasource_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            database TEXT NOT NULL,
            username TEXT NOT NULL,
            secret_ref TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS datasource_catalog_columns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datasource_id TEXT NOT NULL,
            schema_name TEXT,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            data_type TEXT NOT NULL,
            nullable INTEGER NOT NULL,
            ordinal_position INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            refreshed_at TEXT NOT NULL,
            FOREIGN KEY(datasource_id) REFERENCES datasources(datasource_id)
        );

        CREATE INDEX IF NOT EXISTS idx_datasource_catalog_columns_source_table
            ON datasource_catalog_columns(datasource_id, table_name);
        """,
    ),
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS datasource_table_profiles (
            datasource_id TEXT NOT NULL,
            schema_name TEXT,
            table_name TEXT NOT NULL,
            row_count INTEGER,
            table_type TEXT NOT NULL DEFAULT 'unknown',
            description TEXT,
            primary_date_column TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (datasource_id, table_name),
            FOREIGN KEY(datasource_id) REFERENCES datasources(datasource_id)
        );

        CREATE TABLE IF NOT EXISTS datasource_column_profiles (
            datasource_id TEXT NOT NULL,
            schema_name TEXT,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            semantic_type TEXT,
            description TEXT,
            null_ratio REAL,
            distinct_count INTEGER,
            sample_values_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (datasource_id, table_name, column_name),
            FOREIGN KEY(datasource_id) REFERENCES datasources(datasource_id)
        );

        CREATE TABLE IF NOT EXISTS semantic_metrics (
            datasource_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            expression TEXT NOT NULL,
            recommended_table TEXT,
            filters_json TEXT NOT NULL DEFAULT '[]',
            dimensions_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (datasource_id, name),
            FOREIGN KEY(datasource_id) REFERENCES datasources(datasource_id)
        );

        CREATE TABLE IF NOT EXISTS semantic_terms (
            datasource_id TEXT NOT NULL,
            term TEXT NOT NULL,
            description TEXT,
            related_tables_json TEXT NOT NULL DEFAULT '[]',
            related_columns_json TEXT NOT NULL DEFAULT '[]',
            related_metrics_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (datasource_id, term),
            FOREIGN KEY(datasource_id) REFERENCES datasources(datasource_id)
        );

        CREATE TABLE IF NOT EXISTS semantic_marts (
            datasource_id TEXT NOT NULL,
            table_name TEXT NOT NULL,
            description TEXT,
            grain TEXT,
            date_column TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            related_metrics_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (datasource_id, table_name),
            FOREIGN KEY(datasource_id) REFERENCES datasources(datasource_id)
        );

        CREATE TABLE IF NOT EXISTS semantic_join_paths (
            datasource_id TEXT NOT NULL,
            left_table TEXT NOT NULL,
            right_table TEXT NOT NULL,
            join_condition TEXT NOT NULL,
            relationship_type TEXT,
            confidence REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (datasource_id, left_table, right_table, join_condition),
            FOREIGN KEY(datasource_id) REFERENCES datasources(datasource_id)
        );

        CREATE INDEX IF NOT EXISTS idx_table_profiles_datasource
            ON datasource_table_profiles(datasource_id);
        CREATE INDEX IF NOT EXISTS idx_column_profiles_datasource_table
            ON datasource_column_profiles(datasource_id, table_name);
        CREATE INDEX IF NOT EXISTS idx_semantic_marts_datasource_priority
            ON semantic_marts(datasource_id, priority);
        """,
    ),
]
