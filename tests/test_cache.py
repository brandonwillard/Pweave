import pweave
import shutil

# XXX: Debug; remove.
%load_ext autoreload
%autoreload 2

def test_cache():
    """Test caching shell"""
    shutil.rmtree("tests/processors/cache", ignore_errors=True)
    pweave.weave("tests/processors/processor_test.pmd", docmode=True)
    pweave.weave("tests/processors/processor_test.pmd", docmode=True)
    assertSameContent(
        "tests/processors/processor_test.md",
        "tests/processors/processor_cache_ref.md")


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


def test_cache_state():
    r""" Without cache states, reloading a chunk that sets variables does
    **not** affect the corresponding variables in later evaluated chunks
    or inlines.  Here, we check that state functionality basically works.

    """

    test_file = r"""
    \begin{document}
        <<chunk0, cache=True>>=
        x = 0
        @
        <<chunk1, cache=False>>=
        print("blah is {}".format(x))
        @
        A value <%=x%>
        <<chunk2, cache=True>>=

        def blah(x_):
            z = 1 + x_


            print("z={}".format(z))

            return z

        x = 1

        blah(x)

        @
        Another value <%=x%>
    \end{document}
    """

    import tempfile
    tmp_dir = tempfile.mkdtemp()
    cache_dir = os.path.join(tmp_dir, 'cache')
    source_file = os.path.join(tmp_dir, 'test_file.noweb')

    shutil.rmtree(cache_dir, ignore_errors=True)

    parser = pweave.readers.PwebReader(string=test_file)
    parser.parse()
    parsed = parser.parsed

    processor_type = pweave.processors.base.PwebProcessorBase
    processor_type = pweave.processors.jupyter.JupyterProcessor
    processor = processor_type(parsed, 'python', source_file, True, tmp_dir,
                               tmp_dir)

    # processor.db.dict()

    processor.run()

    evald_code_chunks = list(filter(lambda x: x.get('type', None) == 'code', processor.parsed))
    evald_doc_chunks = list(filter(lambda x: x.get('type', None) == 'doc', processor.parsed))

    # import ast
    # import tokenize
    # from io import StringIO
    # tks = list(tokenize.generate_tokens(StringIO("  x = 1\ny=1").readline))
    # tks[0]


def assertSameContent(REF, outfile):
    out = open(outfile)
    ref = open(REF)
    assert (out.read() == ref.read())


if __name__ == '__main__':
    test_cache()
