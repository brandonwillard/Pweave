import pweave
import shutil


def test_cache():

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

    processor_type = pweave.processors.jupyter.JupyterProcessor
    processor = processor_type(parsed, 'python', source_file, True, tmp_dir,
                               tmp_dir)

    # First run; no cache.
    processor.run()

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

if __name__ == '__main__':
    test_cache()
