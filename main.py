if __name__ == "__main__":
    try:
        from apk_placer.ui import main
        raise SystemExit(main())
    except Exception:
        import traceback
        from apk_placer.core import data_directory
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "startup-error.log").write_text(traceback.format_exc(), "utf-8")
        raise
