from app.utils.path_overlap import classify_source_path_overlap


def test_classify_source_path_overlap_exact_normalizes_trailing_slashes():
    assert classify_source_path_overlap("//server/proj-A/Evidence1/", "//server/proj-A/Evidence1") == "exact"


def test_classify_source_path_overlap_identifies_ancestor_paths():
    assert classify_source_path_overlap("//server/proj-A/Evidence1", "//server/proj-A") == "ancestor"


def test_classify_source_path_overlap_identifies_descendant_paths():
    assert classify_source_path_overlap("//server/proj-A", "//server/proj-A/Evidence1/SubFolder") == "descendant"


def test_classify_source_path_overlap_respects_component_boundaries():
    assert classify_source_path_overlap("//server/proj-A/Evidence1", "//server/proj-A/Evidence10") == "none"