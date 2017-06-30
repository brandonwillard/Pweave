"""
Processors that execute code from code chunks
"""
import re
import os
import io
import copy

import logging

import shelve

import dill

from ..config import rcParams

logger = logging.getLogger(__name__)


class PwebProcessorBase(object):
    """ This is a base class that implements sequential chunk caching with
    simple state hooks and code change detection.

    It considers a `cache=True|False` parameter per chunk.

    """

    def __init__(self, parsed, kernel, source, caching,
                 figdir, outdir, always_inline=True):
        self.kernel = kernel
        self.parsed = parsed
        self.source = source
        self.caching = caching
        self.always_inline = always_inline

        self.figdir = figdir
        self.outdir = outdir
        self.executed = []

        self.cwd = os.path.dirname(os.path.abspath(source))
        self.basename = os.path.basename(os.path.abspath(source)).split(".")[0]
        self.pending_code = ""  # Used for multichunk splits

        self.db_filename = None
        self.db = None
        self.cachedir = None

    def run(self):

        self.open()

        # Create directory for figures
        self.ensureDirectoryExists(self.getFigDirectory())

        self.executed = []

        # Term chunk returns a list of dicts, this flattens the results
        for chunk in self.parsed:
            res = self._eval_chunk(chunk)
            if isinstance(res, list):
                self.executed = self.executed + res
            else:
                self.executed.append(res)

        self.isexecuted = True

        self.close()

    def open(self):
        if self.caching:
            self.cachedir = os.path.join(self.cwd, rcParams["cachedir"])
            self.ensureDirectoryExists(self.cachedir)
            self.db_filename = self.cachedir + "/" + self.basename + ".db"
            self.db = shelve.open(self.db_filename)

            logger.info("Opened db {}".format(self.db_filename))

    def close(self):
        if self.db:
            self.db.close()
            logger.info("Closed db {}".format(self.db_filename))

    def ensureDirectoryExists(self, figdir):
        if not os.path.isdir(figdir):
            os.mkdir(figdir)

    def getresults(self):
        #flattened = list(itertools.chain.from_iterable(self.executed))
        return copy.deepcopy(self.executed)

    def get_source(self, source):
        r""" Get the source for a symbol in a string.

        For example, in Python, this method would do something like:

        .. code:

                module_text = self._kernel_eval(
                    "import inspect; print(inspect.getsource(%s))" % source)

        Parameters
        ==========
        source: str
            String containing the symbol for which we want to obtain the
            source code.

        Returns
        =======
        String containing the symbol's source code.
        """
        return source

    def _eval_chunk(self, chunk, **kwargs):
        """ Execute code for a chunk.

        Parameters
        ==========
        chunk: dict
            The chunk to be evaluated.

        Returns
        =======
        The original chunk with new keys containing the evaluated material.
        """
        if chunk['type'] not in ['doc', 'code']:
            return chunk

        chunk_ = chunk.copy()

        # Add defaultoptions to parsed options
        if chunk['type'] == 'code':
            defaults = rcParams["chunk"]["defaultoptions"].copy()
            defaults.update(chunk["options"])
            chunk["options"] = defaults

        # Read the source from file or object
        # XXX TODO: This makes no sense whatsoever; if a chunk completely
        # consists of source defined elsewhere, then there's no body to the
        # chunk and almost none of the standard chunk options are relevant.
        # Essentially, a very different expression should be used altogether;
        # something like the inline statements makes much more sense.

        if 'source' in chunk['options']:
            source = chunk["source"]
            if os.path.isfile(source):
                file_source = io.open(source, "r",
                                      encoding='utf-8').read().rstrip()
                chunk["source"] = "\n" + file_source + "\n" + chunk['source']
            else:
                chunk_text = chunk["source"]
                module_text = self.get_source(source)
                chunk["source"] = module_text.rstrip()
                if chunk_text.strip() != "":
                    chunk["source"] += "\n" + chunk_text

        if chunk['type'] == 'doc':
            return chunk

        if chunk['type'] == 'code':

            logger.info("Processing chunk {} named {} from line {}".format(
                chunk['number'], chunk['options']['name'], chunk['start_line']))

            chunk_src = None
            if not chunk['options']["complete"]:
                self.pending_code += chunk["source"]
                chunk['outputs'] = []
                return chunk
            elif self.pending_code != "":
                chunk_src = chunk["source"]
                # Code from all pending chunks for running the code
                chunk["source"] = self.pending_code + chunk_src
                self.pending_code = ""

            if not chunk['options']['evaluate']:
                chunk['outputs'] = []
                return chunk

            self.pre_run_hook(chunk)
            self._eval_chunk_code(chunk)

            # After executing the code save the figure
            if chunk['options']['fig']:
                chunk['figure'] = self.savefigs(chunk)

            if chunk_src is not None:
                # The code from current chunk for display
                chunk['source'] = chunk_src

        self.post_run_hook(chunk)

        return chunk

    def _code_repr(self, code_str):
        r""" Produces an object for a given string of code to be used for
        detecting valid changes in a chunk's source.

        For instance, if a chunk contains Python code, we can do better than
        simply comparing the raw code strings by using their reduced AST forms.
        .. code:

            import ast
            code_repr = ast.parse(code_str)
            # or
            code_repr = ast.dump(ast.parse(code_str))

        Ideally, this representation takes less effort to evaluate and compare than
        it does to simply compute evaluate a chunk.

        Parameters
        ==========
        code_str: string
            The source as it appears in the chunk.

        Returns
        =======
        An object representing a reduced form of the chunk's
        source better suited for later comparisons.
        """
        return code_str

    def _get_cached(self, chunk, cache_params=None, **kernel_kwds):
        r""" Check the cache for a chunk entry, compare the code in each,
        invalidate all chunks that follow when not equal.

        TODO: Determine, and use, dependency between chunks; only
        invalidate dependent chunks.

        TODO: Consider using a binary diff (e.g.
        https://pypi.python.org/pypi/bsdiff4/1.1.4).

        TODO: Consider chunk dependencies.

        Parameters
        ==========
        chunk: dict
            The chunk to be processed.
        cache_params: object
            Set of parameters to be used by more specific processors.

        Returns
        =======
        The evaluated chunk results.
        """

        chunk_num = chunk['number']
        cached_chunk = self.db.get(str(chunk_num), None)

        if cached_chunk is None or\
                not self._chunks_equal(chunk, cached_chunk):

            logger.info("Cache miss on chunk {}".format(chunk_num))
            outputs = self._kernel_eval(chunk['source'], **kernel_kwds)

            # Create a "pseudo-chunk" that contains fields we might want
            # to compare.
            # TODO: Make the comparison keys a class field?
            cached_chunk = {'source': chunk['source'],
                            'outputs': outputs}

            self.db[str(chunk_num)] = cached_chunk

            # Naive document order-based invalidation.
            for k in self.db.keys():
                if int(k) > chunk_num:
                    self.db.pop(k, None)

        else:
            logger.info("Cache hit on chunk {}".format(chunk_num))
            outputs = cached_chunk['outputs']

        return outputs

    def _chunks_equal(self, chunk, cached_chunk):
        r""" Determine if two chunks are equal.

        Use this method to compute special hashing information (and
        add it to the cache),  determine dependencies between chunks and
        invalidate other chunks in the cache, etc.

        Parameters
        ==========
        chunk: dict
            The chunk for which we want to obtain cached results, or
            compute and add them to the cache.
        cached_chunk: dict
            A cached chunk that corresponds to the current chunk in document
            position order.

        Returns
        =======
        A bool indicating a cache hit (`True`) or miss (`False`)
        """
        compare_keys = set(cached_chunk.keys())
        compare_keys.remove('outputs')
        chunk_ = {p_: chunk[p_] for p_ in compare_keys}
        cached_chunk_ = {p_: cached_chunk[p_] for p_ in compare_keys}
        return dill.dumps(chunk_) == dill.dumps(cached_chunk_)

    def _eval_chunk_code(self, chunk):
        """ Evaluates chunks, generates appropriate output and creates
        potentially new chunks

        Returns
        =======
        A list of evaluated chunks.
        """
        # Handle some legacy chunk parameters.
        cache_params = chunk['options'].get('cache', self.caching)
        cache_chunk = cache_params and self.caching

        chunks = []
        if cache_chunk:
            eval_results = self._get_cached(chunk,
                                            cache_params=cache_params)
        else:
            eval_results = self._kernel_eval(chunk['source'])

        new_chunk = chunk.copy()
        new_chunk["source"] = chunk['source'].rstrip()
        new_chunk["outputs"] = eval_results
        chunks.append(new_chunk)

        # source = ""
        # for eval_res, src_res in eval_results:
        #     if len(eval_res) == 0:
        #         source += src_res
        #     else:
        #         new_chunk = chunk.copy()
        #         new_chunk["source"] = source + src_res.rstrip()
        #         new_chunk["outputs"] = eval_res
        #         chunks.append(new_chunk)
        #         source = ""

        return chunks

    def _save_chunk_state(self, chunk, chunk_data):
        r""" Save the interpreter/engine/kernel state corresponding to a new/updated chunk.

        This method helps in the process of re-producing an engine's state--not just
        output/results--on a per-chunk basis.  The state generally consist of
        global and local environments (e.g. variables, loaded libraries, etc.)

        Parameters
        ==========
        chunk: dict
            The chunk to save.

        chunk_data: dict
            The processed chunk data.

        Returns
        =======

        """

        # self.session_file = getattr(self, 'session_file',
        #                             'chunk-{}'.format(chunk_id))
        # chunk_data['session_filename'] = self.session_file
        # self.loadstring("""
        # import dill; session_pickler = dill.dump_session({})
        # """.format(self.session_file))
        pass

    def _load_chunk_state(self, chunk, chunk_data):
        r""" Load the interpreter/engine/kernel state corresponding to a cached chunk.

        This method serves to re-produce an engine's state--not just
        output/results--on a per-chunk basis.  The state generally consist of
        global and local environments (e.g. variables, loaded libraries, etc.)

        Parameters
        ==========
        chunk: dict
            The chunk to save.

        chunk_data: dict
            The processed chunk data.

        Returns
        =======
        """

        # self.loadstring("""
        # import dill; session_unpickler = dill.load_session({})
        # """.format(chunk_data['session_filename']))
        pass

    def post_run_hook(self, chunk):
        pass

    def pre_run_hook(self, chunk):
        pass

    def init_matplotlib(self):
        pass

    def savefigs(self, chunk):
        pass

    def getFigDirectory(self):
        return os.path.join(self.outdir, self.figdir)

    def load_shell(self, chunk):
        pass

    def _kernel_eval(self, code_str, **kwargs):
        r""" Evaluate a code string in the kernel.

        Parameters
        ==========
        code_str: str
            Source string for code to be executed.

        Returns
        =======
        A list of outputs.
        """
        pass

    def load_inline_string(self, code_string):
        pass

    def add_echo(self, code_str):
        return 'print(%s),' % code_str
