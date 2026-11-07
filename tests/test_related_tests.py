from scripts.related_tests import pick_tests


def test_a_core_module_picks_its_own_test_and_every_test_that_imports_it():
    picked = pick_tests(["sida/storage.py"])
    assert "tests/test_storage.py" in picked
    assert "tests/test_webapp.py" not in picked  # webapp reaches storage only through other modules
    assert "tests/experts/site/test_context3d.py" in pick_tests(["sida/experts/site/context3d.py"])


def test_api_modules_also_pick_the_web_api_tests():
    assert "tests/test_webapp.py" in pick_tests(["sida/board_api.py"])
    assert "tests/test_webapp.py" in pick_tests(["sida/experts/site/api.py"])


def test_other_files_map_by_folder_and_shared_test_setup_runs_everything():
    assert pick_tests(["tests/test_board.py", "docs/web-ui.md"]) == ["tests/test_board.py"]
    assert pick_tests(["agents/11_site_reader.md"]) == ["tests/test_agent_prompts.py"]
    assert pick_tests(["collector/app.py"]) == ["tests/collector"]
    assert pick_tests(["relay/app.py"]) == ["tests/relay"]
    assert "tests/experts/site/test_build_terrain_pack.py" in pick_tests(["scripts/build_terrain_pack.py"])
    assert pick_tests(["sida/board.py", "tests/conftest.py"]) == ["tests"]
    assert pick_tests(["tests/test_removed_in_this_branch.py", "README.md"]) == []
