def test_file_write():
    f = open("test_env.txt", "w")
    f.write("ready")
    f.close()  # If an exception happens before this line, the file stays open leaking resources