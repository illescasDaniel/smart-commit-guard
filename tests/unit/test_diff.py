from smart_commit_guard.diff import parse_added_lines

DIFF = """diff --git a/src/app.py b/src/app.py
index 111..222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 import os
-OLD = "removed-secret"
+NEW = 1
+OTHER = 2
@@ -10,0 +12,1 @@
+LATE = 3
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
"""


def test_given_a_diff_when_parsing_then_only_added_lines_with_new_line_numbers_are_returned():
	lines = parse_added_lines(DIFF)
	assert [(l.path, l.number, l.text) for l in lines] == [
		("src/app.py", 2, "NEW = 1"), ("src/app.py", 3, "OTHER = 2"), ("src/app.py", 12, "LATE = 3")]


def test_given_a_removed_secret_when_parsing_then_it_is_ignored():
	assert all("removed-secret" not in l.text for l in parse_added_lines(DIFF))


def test_given_a_binary_diff_when_parsing_then_nothing_is_returned_for_it():
	assert all(l.path != "img.png" for l in parse_added_lines(DIFF))


def test_given_a_deleted_file_when_parsing_then_nothing_is_returned():
	diff = "diff --git a/x b/x\ndeleted file mode 100644\n--- a/x\n+++ /dev/null\n@@ -1 +0,0 @@\n-SECRET = 1\n"
	assert parse_added_lines(diff) == []
