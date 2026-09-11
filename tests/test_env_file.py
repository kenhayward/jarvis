"""The one definition of a line of `.env`.

It lived in server.py, and install.py cannot import server.py -- whose
imports need the venv install.py has not built yet. So it moved to a module
of its own, and this pins that it moved rather than being copied: three
copies once disagreed, and the gap let a POSTed value redirect the binary
the brain is spawned from (see env_file.py).
"""
import env_file
import server


def test_the_server_uses_the_one_definition_not_a_copy():
    assert server._parse_env_lines is env_file.parse_env_lines


def test_it_still_reads_a_line_the_way_the_server_always_has():
    text = '# a comment\nA=1\n  B = "two" \nC=\'three\'\nnot a line\n'
    assert env_file.parse_env_lines(text) == [("A", "1"), ("B", "two"), ("C", "three")]


def test_every_line_separator_python_knows_is_a_line_separator():
    # The reason it is one function: splitlines() splits on ten characters,
    # and a writer that forbade only three let a value smuggle in a line.
    assert env_file.parse_env_lines("A=1\x0bB=2") == [("A", "1"), ("B", "2")]
