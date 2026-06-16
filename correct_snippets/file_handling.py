def test_file_write():
    # SyntaxError: expected an indented block after 'with' statement
    with open("test_env.txt", "w") as f:
    f.write("ready")