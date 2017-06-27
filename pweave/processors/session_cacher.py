import io
import dill

def _dump_session(f, byref=False, main=None):
    """ From dill.dump_session.
    """
    import __main__ as _main_module
    protocol = dill.settings['protocol']
    if main is None:
        main = _main_module
    if byref:
        from dill.dill import _stash_modules
        main = _stash_modules(main)
    pickler = dill.Pickler(f, protocol)
    pickler._main = main
    pickler._byref = False
    pickler._recurse = False
    pickler._session = True
    pickler.dump(main)
    return pickler


def _load_session(f, main=None):
    """ From dill.load_session.
    """
    if main is None:
        import __main__ as _main_module
        main = _main_module
    unpickler = dill.Unpickler(f)
    unpickler._main = main
    unpickler._session = True
    module = unpickler.load()
    unpickler._session = False
    main.__dict__.update(module.__dict__)
    from dill.dill import _restore_modules
    _restore_modules(main)
    return unpickler



