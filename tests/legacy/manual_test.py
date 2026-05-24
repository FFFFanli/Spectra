import io

from backend.db_utils import get_database_schema, save_file_to_duckdb


__test__ = False


def main():
    csv_data = "name,age,score\nAlice,25,88.5\nBob,,92.0\nCharlie,30,85.0"
    file_obj = io.StringIO(csv_data)
    _, table_name = save_file_to_duckdb(file_obj, "test.csv", "user_data")
    print(f"saved table: {table_name}")
    print(get_database_schema())


if __name__ == "__main__":
    main()
