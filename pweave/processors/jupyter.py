# -*- coding: utf-8 -*-

import os
import textwrap
import logging

from jupyter_client.manager import start_new_kernel
from nbformat.v4 import output_from_msg
from IPython.core import inputsplitter

from .. import config
from .base import PwebProcessorBase
from . import subsnippets

try:
    from queue import Empty  # Python 3
except ImportError:
    from Queue import Empty  # Python 2

logger = logging.getLogger(__name__)

class JupyterProcessor(PwebProcessorBase):
    """Generic Jupyter processor, should work with any kernel"""

    def __init__(self, *args, **kwargs):
        super(JupyterProcessor, self).__init__(*args, **kwargs)

        self.extra_arguments = kwargs.get('extra_arguments', None)
        self.timeout = kwargs.get('timeout', None)
        self.cwd = os.path.abspath(self.outdir)

    def open(self):
        super(JupyterProcessor, self).open()

        self.km, self.kc = start_new_kernel(
            kernel_name=self.kernel,
            extra_arguments=self.extra_arguments,
            stderr=open(os.devnull, 'w'),
            cwd=self.cwd)
        self.kc.allow_stdin = False

        logger.info("Started {} kernel ({}) in {}".format(
            self.kernel, self.km.connection_file, self.cwd))

    def close(self):
        super(JupyterProcessor, self).close()

        logger.info("Stopping {} kernel ({}) in {}".format(
            self.kernel, self.km.connection_file, self.cwd))

        self.kc.stop_channels()
        self.km.shutdown_kernel(now=True)

    def run_cell(self, src):

        outs = []

        def process_msg(msg, outs=outs):

            msg_type = msg['msg_type']
            content = msg['content']

            if msg_type == 'status':
                return
            elif msg_type == 'execute_input':
                return
            elif msg_type == 'clear_output':
                outs = []
                return
            elif msg_type.startswith('comm'):
                return

            try:
                out = output_from_msg(msg)
            except ValueError:
                logger.error("unhandled iopub msg: {}".format(msg_type))
            else:
                outs.append(out)

        reply = self.kc.execute_interactive(src, timeout=self.timeout,
                                            output_hook=process_msg)

        return outs


    def _kernel_eval(self, code_str, **kwargs):

        # Get rid of unnecessary indentations
        code_str_ = textwrap.dedent(code_str)

        eval_res = self.run_cell(code_str_)

        return eval_res

    # TODO: Put this stuff in the writer objects.
    # def _eval_output(self, code_str):
    #     r""" Format the raw kernel output to a basic chunk output.
    #     """
    #     from nbconvert import filters
    #     outputs = self._kernel_eval(code_str)
    #     result = ""
    #     for out in outputs:
    #         if out["output_type"] == "stream":
    #             result += out["text"]
    #         elif out["output_type"] == "error":
    #             result += filters.strip_ansi("".join(out["traceback"]))
    #         elif "text/plain" in out["data"]:
    #             result += out["data"]["text/plain"]
    #         else:
    #             result = ""
    #     return result

    def get_source(self, source):
        # XXX: Isn't this Python-specific.  A "Jupyter" processor shouldn't
        # be.
        module_text = self._kernel_eval(
            "import inspect; print(inspect.getsource(%s))" % source)
        return module_text


class IPythonProcessor(JupyterProcessor):
    """Contains IPython specific functions"""

    def __init__(self, *args, **kwargs):
        super(IPythonProcessor, self).__init__(*args, **kwargs)

        if config.rcParams["usematplotlib"]:
            self.init_matplotlib()

    def init_matplotlib(self):
        self._kernel_eval(subsnippets.init_matplotlib)

    def pre_run_hook(self, chunk):
        f_size = """matplotlib.rcParams.update({"figure.figsize" : (%i, %i)})""" % chunk[
            "f_size"]
        f_dpi = """matplotlib.rcParams.update({"savefig.dpi" : %i})""" % chunk[
            "dpi"]
        self._kernel_eval("\n".join([f_size, f_dpi]))

    def _print_src(src):
        return "print({})".format(src)

    # def loadterm(self, code_str, **kwargs):
    #     splitter = inputsplitter.IPythonInputSplitter()
    #     code_lines = code_str.lstrip().splitlines()
    #     sources = []
    #     outputs = []
    #     for line in code_lines:
    #         if splitter.push_accepts_more():
    #             splitter.push_line(line)
    #         else:
    #             code_str = splitter.source
    #             sources.append(code_str)
    #             _, out = self._kernel_eval(code_str)
    #             # print(out)
    #             outputs.append(out)
    #             splitter.reset()
    #             splitter.push_line(line)
    #     if splitter.source != "":
    #         code_str = splitter.source
    #         sources.append(code_str)
    #         _, out = self._kernel_eval(code_str)
    #         outputs.append(out)
    #     return((sources, outputs))

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

    def _put_cached(self, chunk, outputs, **kwargs):
        r"""

        TODO: Consider sequentially saving state with `dill`'s session saving
        functionality.
        Additionally, consider using a binary diffs (e.g.
        https://pypi.python.org/pypi/bsdiff4/1.1.4) to sequentially save and
        re-load the interpreter state in a chunk-wise fashion, while avoiding
        exponential growth of the cache.

        """
        super(IPythonProcessor, self)._put_cached(chunk, outputs, **kwargs)

