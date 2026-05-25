from __future__ import annotations

from data_agent_backend.models.common import BackendError, utc_now_iso
from data_agent_backend.models.datasources import DatasourceCatalogColumn, DatasourceKind, DatasourceRecord
from data_agent_backend.storage.sqlite import SQLiteStore, dumps_json, loads_json


class DatasourceRegistry:
    def __init__(self, sqlite: SQLiteStore) -> None:
        self.sqlite = sqlite

    def create(self, record: DatasourceRecord) -> DatasourceRecord:
        self.sqlite.execute(
            """
            INSERT INTO datasources(
                datasource_id, name, kind, host, port, database, username, secret_ref,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.datasource_id,
                record.name,
                record.kind.value,
                record.host,
                record.port,
                record.database,
                record.username,
                record.secret_ref,
                dumps_json(record.metadata),
                record.created_at,
                record.updated_at,
            ),
        )
        return self.get(record.datasource_id)

    def get(self, datasource_id: str) -> DatasourceRecord:
        row = self.sqlite.query_one("SELECT * FROM datasources WHERE datasource_id = ?", (datasource_id,))
        if row is None:
            raise BackendError("NOT_FOUND", "Datasource was not found.", {"datasource_id": datasource_id})
        return DatasourceRecord(
            datasource_id=row["datasource_id"],
            name=row["name"],
            kind=DatasourceKind(row["kind"]),
            host=row["host"],
            port=row["port"],
            database=row["database"],
            username=row["username"],
            secret_ref=row["secret_ref"],
            metadata=loads_json(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list(self) -> list[DatasourceRecord]:
        rows = self.sqlite.query_all("SELECT datasource_id FROM datasources ORDER BY created_at")
        return [self.get(row["datasource_id"]) for row in rows]

    def replace_catalog(self, datasource_id: str, columns: list[DatasourceCatalogColumn]) -> list[DatasourceCatalogColumn]:
        self.get(datasource_id)
        refreshed_at = utc_now_iso()
        with self.sqlite.connect() as conn:
            conn.execute("DELETE FROM datasource_catalog_columns WHERE datasource_id = ?", (datasource_id,))
            for column in columns:
                conn.execute(
                    """
                    INSERT INTO datasource_catalog_columns(
                        datasource_id, schema_name, table_name, column_name, data_type,
                        nullable, ordinal_position, metadata_json, refreshed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datasource_id,
                        column.schema_name,
                        column.table_name,
                        column.column_name,
                        column.data_type,
                        int(column.nullable),
                        column.ordinal_position,
                        dumps_json(column.metadata),
                        column.refreshed_at or refreshed_at,
                    ),
                )
        return self.get_catalog(datasource_id)

    def get_catalog(self, datasource_id: str, table_name: str | None = None) -> list[DatasourceCatalogColumn]:
        self.get(datasource_id)
        if table_name:
            rows = self.sqlite.query_all(
                """
                SELECT * FROM datasource_catalog_columns
                WHERE datasource_id = ? AND table_name = ?
                ORDER BY table_name, ordinal_position
                """,
                (datasource_id, table_name),
            )
        else:
            rows = self.sqlite.query_all(
                """
                SELECT * FROM datasource_catalog_columns
                WHERE datasource_id = ?
                ORDER BY table_name, ordinal_position
                """,
                (datasource_id,),
            )
        return [
            DatasourceCatalogColumn(
                datasource_id=row["datasource_id"],
                schema_name=row["schema_name"],
                table_name=row["table_name"],
                column_name=row["column_name"],
                data_type=row["data_type"],
                nullable=bool(row["nullable"]),
                ordinal_position=row["ordinal_position"],
                metadata=loads_json(row["metadata_json"]),
                refreshed_at=row["refreshed_at"],
            )
            for row in rows
        ]

