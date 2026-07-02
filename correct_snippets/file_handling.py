def test_file_write()
    with open("test_env.txt", "w") as f:
        f.write("ready")
    # File is guaranteed to close here
    # Unused and confusing variable
    temp_var = 12345
    pass
