from biasradar.db import get_supabase


def main() -> None:
    supabase = get_supabase()

    response = supabase.table("topics").select("*").limit(5).execute()

    print(response.data)


if __name__ == "__main__":
    main()
