import pickle
import pytest

from texra_blueprint.Packages.texra_patches import (
    _SafePauxUnpickler, _safe_paux_loads)


def test_plain_containers_pass():
    payload = pickle.dumps({"HTML5": {"label": {"url": "x.html", "ref": "1"}}})
    assert _safe_paux_loads(payload) == {"HTML5": {"label": {"url": "x.html", "ref": "1"}}}


class _Evil:
    pass


def test_arbitrary_class_refused():
    payload = pickle.dumps(_Evil())
    assert _safe_paux_loads(payload) == {}
    import io
    with pytest.raises(pickle.UnpicklingError):
        _SafePauxUnpickler(io.BytesIO(payload)).load()


def test_garbage_returns_empty():
    assert _safe_paux_loads(b"not a pickle") == {}
    assert _safe_paux_loads(pickle.dumps([1, 2])) == {}
