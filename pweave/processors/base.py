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
            os.makedirs(self.cachedir, exist_ok=True)

            self.db_filename = self.cachedir + "/" + self.basename + ".db"
            self.db = shelve.open(self.db_filename)

            logger.info("Opened db {}".format(self.db_filename))

    def close(self):
        if self.db:
            self.db.close()
            logger.info("Closed db {}".format(self.db_filename))

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

            new_chunk = self._eval_chunk_code(chunk)

            # After executing the code save the figure
            if new_chunk['options']['fig']:
                self.save_figs(new_chunk)

        self.post_run_hook(new_chunk)

        return new_chunk

    def _eval_cached(self, chunk, **kwargs):
        r""" Check the cache for a chunk entry and evaluate when missing.

        XXX: This method adds a key to the chunk ('from_cache': bool).

        Parameters
        ==========
        chunk: dict
            The chunk to be processed.

        Returns
        =======
        The evaluated chunk results.
        """

        cached_chunk = self._get_cached(chunk)

        c_ = self._chunk_hash(chunk)
        cc_ = self._chunk_hash(cached_chunk)

        if c_ != cc_:

            outputs = self._kernel_eval(chunk['source'], **kwargs)

            # TODO: Method for determining what's to be cached.
            self._put_cached(chunk, outputs)

            logger.info("Cache miss on chunk {}".format(chunk['number']))
            chunk['from_cache'] = False

        else:
            outputs = cached_chunk['outputs']

            logger.info("Cache hit on chunk {}".format(chunk['number']))
            chunk['from_cache'] = True

        return outputs

    def _get_cached(self, chunk, **kwargs):
        r""" Get a chunk in the cache.

        Parameters
        ==========
        chunk: dict
            The chunk we're caching.

        Returns
        =======
        Cached chunk, if found, or `None`.
        """

        chunk_key = str(chunk['number'])
        cached_chunk = self.db.get(chunk_key, None)

        return cached_chunk

    def _put_cached(self, chunk, outputs, **kwargs):
        r""" Put evaluated chunk into the cache.

        TODO: The Jupyter client API has an `inspect` function that could be
        used to inquire about variables by name for an arbitrary kernel.
        Consider using this as a general means of specifying a list of variables
        in the `cache` chunk option that can be assigned "keyed against".  One
        might be able to implement a slightly less naive version of chunk
        dependency using the `found` value in the results of `inspect`.

        Parameters
        ==========
        chunk: dict
            The chunk we're caching.
        outputs: list
            The outputs computed for the chunk.
        """

        chunk = chunk.copy()
        chunk['outputs'] = outputs

        chunk_key = str(chunk['number'])
        self.db[chunk_key] = chunk

        #
        # Naive document order-based invalidation.
        #
        # TODO: This might need to be improved to handle inline chunks that
        # only print (even though one can't really be certain there are
        # no side effects).
        chunk_num = chunk['number']
        for k in self.db.keys():
            if int(k) > chunk_num:
                self.db.pop(k, None)


    def _chunk_hash(self, chunk,
                    hash_keys=('source'),
                    **kwargs):
        r""" Produce the values by which cached chunks are compared.

        Use this method to compute determine which things are compared
        and how.

        TODO: Would be so much better to have chunk objects that implement their
        own hash and/or `__eq__` methods.
        XXX TODO: Some keys that affect `outputs` are not included (e.g.
        `options` relating to figures, terminal output, wrapping, etc.)  Logic
        should be added to account for those.

        Parameters
        ==========
        chunk: dict
            The chunk for which we want a value with which
            to test equality.
        hash_keys: dict
            The keys (existing in `chunk`) used to produce the
            comparison object with the default implementation
            (i.e. `dill.dumps`).

        Returns
        =======
        Some object that implements `__eq__`; presumably a string, though.
        """
        if not isinstance(chunk, dict):
            return None

        res = chunk.get('cache_hash', None)

        if res is None:
            chunk_ = {p_: chunk.get(p_, None) for p_ in hash_keys}
            res = dill.dumps(chunk_)
            chunk['cache_hash'] = res

        return res

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

        new_chunk = chunk.copy()

        if chunk.get('inline', False) and\
                chunk['options'].get('print', False):
            new_chunk['source'] = self._print_cmd(new_chunk['source'])

        if cache_chunk:
            eval_results = self._eval_cached(new_chunk)
        else:
            eval_results = self._kernel_eval(new_chunk['source'])

        # TODO: Should we really strip newlines here?
        new_chunk["source"] = new_chunk['source'].rstrip()
        new_chunk["outputs"] = eval_results

        return new_chunk

    def _print_cmd(self, src):
        r""" Command used to [pretty] print the results of a line of source.

        Parameters
        ==========
        src: string
            The source to print.

        Returns
        =======
        A string representing a command that prints the results of the given
        source string.
        """
        return src

    def post_run_hook(self, chunk):
        pass

    def pre_run_hook(self, chunk):
        pass

    def save_figs(self, chunk):
        r""" Save the evaluated image data and put the resulting filenames in
        the chunk metadata.

        XXX: This changes chunk state.

        Parameters
        ==========
        chunk: dict
            The chunk with image data.

        Returns
        =======
        Boolean indicating whether or not image data was found and processed.
        """

        # TODO: This should probably be in a "formatter".
        # fig_entries = filter(lambda x: x.get('output_type', None) == 'display_data',
        #                      chunk['outputs'])
        # os.makedirs(self.figdir, exist_ok=True)
        # found = False
        # for fig_data in fig_entries:
        #     fig_fname = ...
        #     fig_data['metadata']['filename'] = fig_fname
        #     found = True
        # return found
        pass

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
