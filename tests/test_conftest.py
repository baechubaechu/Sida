from tests.conftest import long_test_names


def test_a_test_name_made_from_a_big_bytes_value_is_caught():
    huge = "tests/test_board.py::test_photo[" + "\\x00" * 5_000_000 + "]"
    found = long_test_names(["tests/test_board.py::test_photo[over_20mb]", huge])
    assert len(found) == 1 and len(found[0]) < 200
