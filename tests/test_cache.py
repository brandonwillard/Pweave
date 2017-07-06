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
        print("x is {}".format(x))
        @
        A value <%=x%>

        <<chunk2, fig=True, cache=True>>=
        import matplotlib.pylab as plt
        plt.plot(range(5), range(5))
        plt.show()
        @

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

    # processor_type = pweave.processors.base.PwebProcessorBase
    processor_type = pweave.processors.jupyter.JupyterProcessor
    processor = processor_type(parsed, 'python', source_file, True, tmp_dir,
                               tmp_dir)

    # First run, no cache.
    processor.run()
    # %debug --breakpoint ./pweave/processors/base.py:318 processor.run()

    evald_code_chunks = list(filter(lambda x: x.get('type', None) == 'code',
                                    processor.executed))

    assert not evald_code_chunks[0]['from_cache']
    assert not evald_code_chunks[1].get('from_cache', None)

    assert not evald_code_chunks[2]['from_cache']
    assert evald_code_chunks[2]['inline']

    # TODO: Test for IPythonProcessor
    # Make sure it wrapped with `print`
    # assert evald_code_chunks[2]['source'] == 'print(x)'

    assert evald_code_chunks[2]['outputs'][0]['data']['text/plain'] == '0'
    assert evald_code_chunks[3]['outputs'][1]['output_type'] == 'display_data'

    # This one should use the cache.
    processor.run()

    cached_code_chunks = list(filter(lambda x: x.get('type', None) == 'code',
                                     processor.executed))

    assert cached_code_chunks[0]['from_cache']
    # The output from this chunk should be an exception, since its source depends on
    # values that weren't re-introduced to the environment (they were in the
    # preceding chunk that was reloaded from the cache).
    #
    # We could consider re-running preceding chunks in this situation, but
    # control might be better left to the user.
    assert not cached_code_chunks[1].get('from_cache', None)

    assert cached_code_chunks[2]['from_cache']
    assert cached_code_chunks[2]['inline']
    assert cached_code_chunks[2]['outputs'][0]['data']['text/plain'] == '0'

    assert cached_code_chunks[3]['from_cache']
    assert evald_code_chunks[3]['outputs'][1]['output_type'] == 'display_data'

def scratch_shelve():

    # from functools import partial
    # ip = get_ipython()
    # processor.kc.execute_interactive("x=1\nx\nz=1\nz",
    #                                  output_hook=partial(
    #                                      processor.kc._output_hook_kernel,
    #                                      ip.display_pub.session,
    #                                      ip.display_pub.pub_socket,
    #                                      ip.display_pub.parent_header)
    #                                  # processor.kc._output_hook_kernel
    #                                  # processor.kc._output_hook_default
    #                                  # lambda x: print(x)
    #                                  )

    import shelve
    import dill
    from collections import OrderedDict

    # import tempfile
    # tmp_dir = tempfile.mkdtemp()
    # cache_dir = os.path.join(tmp_dir, 'cache')

    # shutil.rmtree(cache_dir, ignore_errors=True)

    # XXX: Hackish replacement
    shelve.Pickler = dill.Pickler
    shelve.Unpickler = dill.Unpickler

    s_ = shelve.open(os.path.join('/tmp', 'test_shelf.db'))
    # s_.cache = OrderedDict()

    obj_ = {1: 'hi', 2: [4, 5]}
    s_['1'] = obj_

    s_.get('1')
    s_.close()


def assertSameContent(REF, outfile):
    out = open(outfile)
    ref = open(REF)
    assert (out.read() == ref.read())


if __name__ == '__main__':
    test_cache()
