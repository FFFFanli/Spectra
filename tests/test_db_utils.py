import io
import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

import backend.db_utils as db_utils


class DbUtilsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name)
        self.db_path = self.base / "test.duckdb"
        self.artifacts_dir = self.base / "artifacts"
        self.artifacts_dir.mkdir()

        self.old_db_path = db_utils.DB_PATH
        self.old_artifacts_dir = db_utils.ARTIFACTS_DIR
        self.old_artifact_relpath = db_utils.artifact_relpath
        self.old_ensure_directories = db_utils.ensure_directories

        db_utils.DB_PATH = str(self.db_path)
        db_utils.ARTIFACTS_DIR = self.artifacts_dir
        db_utils.artifact_relpath = lambda path: Path(path).name
        db_utils.ensure_directories = lambda: self.artifacts_dir.mkdir(exist_ok=True)

        self.addCleanup(self._restore_patches)

    def _restore_patches(self):
        db_utils.DB_PATH = self.old_db_path
        db_utils.ARTIFACTS_DIR = self.old_artifacts_dir
        db_utils.artifact_relpath = self.old_artifact_relpath
        db_utils.ensure_directories = self.old_ensure_directories

    def test_save_csv_to_duckdb_sanitizes_columns(self):
        csv_bytes = io.BytesIO("姓名,总 分,score-rate\n张三,95,0.9\n李四,88,0.8\n".encode("utf-8"))

        df, table_name = db_utils.save_file_to_duckdb(csv_bytes, "学生 成绩.csv")

        self.assertEqual(table_name, "学生_成绩")
        self.assertEqual(list(df.columns), ["姓名", "总_分", "score_rate"])

        with duckdb.connect(str(self.db_path)) as con:
            columns = con.execute('DESCRIBE "学生_成绩"').fetchall()
            rows = con.execute('SELECT COUNT(*) FROM "学生_成绩"').fetchone()[0]

        self.assertEqual(rows, 2)
        self.assertEqual([col[0] for col in columns], ["姓名", "总_分", "score_rate"])

    def test_save_excel_to_duckdb(self):
        excel_buffer = io.BytesIO()
        pd.DataFrame({"订单ID": [1, 2], "销售 额": [100, 200]}).to_excel(excel_buffer, index=False)
        excel_buffer.seek(0)

        df, table_name = db_utils.save_file_to_duckdb(excel_buffer, "销售记录.xlsx")

        self.assertEqual(table_name, "销售记录")
        self.assertEqual(list(df.columns), ["订单ID", "销售_额"])

        with duckdb.connect(str(self.db_path)) as con:
            values = con.execute('SELECT SUM("销售_额") FROM "销售记录"').fetchone()[0]

        self.assertEqual(values, 300)

    def test_get_database_schema_returns_table_structure_and_sample(self):
        csv_bytes = io.BytesIO("city,value\nshanghai,10\nbeijing,20\n".encode("utf-8"))
        db_utils.save_file_to_duckdb(csv_bytes, "city.csv", table_name="city_stats")

        schema = db_utils.get_database_schema()

        self.assertIn("city_stats", schema)
        self.assertIn('"city" VARCHAR', schema)
        self.assertIn("shanghai", schema)


if __name__ == "__main__":
    unittest.main()
