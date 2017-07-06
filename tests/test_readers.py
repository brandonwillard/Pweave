import pweave

def test_inline():
    r""" Test that inline statements are processed as complete chunks.
    Also checks that noweb blocks can contain whitespace before delimiters.
    """

    test_file = r"""
    \begin{document}
        <<chunk1, cache=False>>=
        x = 0
        @
        A value <%=x%>
        <<chunk2, cache=True>>=
        x = 1
        @
        Another value <%=x%>
    \end{document}
    """

    parser = pweave.readers.PwebReader(string=test_file)
    parser.parse()
    parsed = parser.parsed

    expected_res = [{'content': '\n\\begin{document}\n',
                     'number': 1,
                     'start_line': 3,
                     'type': 'doc'},
                    {'content': '    x = 0', 'number': 1,
                     'options': {
                         'cache': False, 'name': 'chunk1',
                         'option_string': 'name = "chunk1", cache=False'},
                     'start_line': 5,
                     'type': 'code'},
                    {'content': '    A value ',
                     'number': 2, 'start_line': 6,
                     'type': 'doc'},
                    {'content': 'x',
                     'inline': True, 'number': 2,
                     'options': {'print': True},
                     'start_line': 6, 'type': 'code'},
                    {'content': '\n',
                     'number': 3, 'start_line': 7, 'type': 'doc'},
                    {'content': '    x = 1', 'number': 3,
                     'options': {
                         'cache': True, 'name': 'chunk2',
                         'option_string': 'name = "chunk2", cache=True'},
                     'start_line': 9, 'type': 'code'
                     },
                    {'content': '    Another value ',
                     'number': 4, 'start_line': 10, 'type': 'doc'},
                    {'content': 'x', 'inline': True, 'number': 4,
                     'options': {'print': True},
                     'start_line': 10,
                     'type': 'code'},
                    {'content': '\n\\end{document}\n',
                     'number': 5, 'type': 'doc'}]

    assert parsed == expected_res

def test_markdown():
    """Test markdown reader"""
    pweave.weave("tests/readers/markdown_reader.pmd", doctype = "pandoc", informat = "markdown")
    assertSameContent("tests/readers/markdown_reader.md", "tests/readers/markdown_reader_ref.md")

def test_script():
    """Test markdown reader"""
    doc = pweave.Pweb("tests/publish/publish_test.txt", informat="script")
    doc.tangle()
    assertSameContent("tests/publish/publish_test.py",
                      "tests/publish/publish_test_REF.py")

def test_url():
    pweave.weave("http://files.mpastell.com/formatters_test.pmd", output = "tests/formats/formatters_url.pmd")
    assertSameContent("tests/formats/formatters_url.pmd", "tests/formats/formatters_test_REF.markdown")

def assertSameContent(REF, outfile):
    out = open(outfile)
    ref = open(REF)
    assert (out.read() == ref.read())

if __name__ == '__main__':
    test_markdown()
    test_script()
    test_url()
