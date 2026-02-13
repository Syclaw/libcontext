"""Tests for the AST inspector module."""

from __future__ import annotations

from libcontext.inspector import inspect_source, is_public_member

# ---------------------------------------------------------------------------
# Simple function extraction
# ---------------------------------------------------------------------------

SAMPLE_FUNCTION = '''
def greet(name: str, greeting: str = "Hello") -> str:
    """Say hello to someone."""
    return f"{greeting}, {name}!"
'''


def test_extract_simple_function():
    module = inspect_source(SAMPLE_FUNCTION, module_name="test_mod")

    assert len(module.functions) == 1
    func = module.functions[0]

    assert func.name == "greet"
    assert func.return_annotation == "str"
    assert func.docstring == "Say hello to someone."
    assert not func.is_async

    # Parameters
    assert len(func.parameters) == 2
    assert func.parameters[0].name == "name"
    assert func.parameters[0].annotation == "str"
    assert func.parameters[0].default is None
    assert func.parameters[1].name == "greeting"
    assert func.parameters[1].annotation == "str"
    assert func.parameters[1].default == "'Hello'"


# ---------------------------------------------------------------------------
# Async function
# ---------------------------------------------------------------------------

SAMPLE_ASYNC = '''
async def fetch(url: str, *, timeout: int = 30) -> bytes:
    """Fetch data from a URL."""
    ...
'''


def test_extract_async_function():
    module = inspect_source(SAMPLE_ASYNC, module_name="test_mod")

    func = module.functions[0]
    assert func.is_async
    assert func.name == "fetch"
    assert func.return_annotation == "bytes"

    # keyword-only param
    kw_params = [p for p in func.parameters if p.kind == "KEYWORD_ONLY"]
    assert len(kw_params) == 1
    assert kw_params[0].name == "timeout"
    assert kw_params[0].default == "30"


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

SAMPLE_CLASS = '''
class Animal:
    """A base animal class."""

    species: str = "Unknown"

    def __init__(self, name: str, age: int = 0) -> None:
        """Initialize the animal."""
        self.name = name
        self.age = age

    def speak(self) -> str:
        """Make a sound."""
        return "..."

    def _internal(self) -> None:
        """Private method."""
        pass

    @property
    def info(self) -> str:
        """Get animal info."""
        return f"{self.name} ({self.age})"

    @classmethod
    def from_dict(cls, data: dict) -> "Animal":
        """Create from dictionary."""
        return cls(**data)

    @staticmethod
    def valid_species() -> list[str]:
        """List valid species."""
        return []
'''


def test_extract_class():
    module = inspect_source(SAMPLE_CLASS, module_name="test_mod")

    assert len(module.classes) == 1
    cls = module.classes[0]

    assert cls.name == "Animal"
    assert cls.docstring == "A base animal class."

    # Class variables
    assert len(cls.class_variables) == 1
    assert cls.class_variables[0].name == "species"
    assert cls.class_variables[0].annotation == "str"

    # Methods
    method_names = [m.name for m in cls.methods]
    assert "__init__" in method_names
    assert "speak" in method_names
    assert "_internal" in method_names
    assert "info" in method_names
    assert "from_dict" in method_names
    assert "valid_species" in method_names

    # Check decorators
    info_method = next(m for m in cls.methods if m.name == "info")
    assert info_method.is_property

    from_dict = next(m for m in cls.methods if m.name == "from_dict")
    assert from_dict.is_classmethod

    valid = next(m for m in cls.methods if m.name == "valid_species")
    assert valid.is_staticmethod


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------

SAMPLE_INHERITANCE = '''
class Dog(Animal, Serializable):
    """A dog."""
    pass
'''


def test_extract_bases():
    module = inspect_source(SAMPLE_INHERITANCE, module_name="test_mod")

    cls = module.classes[0]
    assert cls.bases == ["Animal", "Serializable"]


# ---------------------------------------------------------------------------
# __all__ extraction
# ---------------------------------------------------------------------------

SAMPLE_ALL = """
__all__ = ["public_func", "PublicClass"]

def public_func():
    pass

def _private_func():
    pass

class PublicClass:
    pass

class _PrivateClass:
    pass
"""


def test_extract_all():
    module = inspect_source(SAMPLE_ALL, module_name="test_mod")

    assert module.all_exports == ["public_func", "PublicClass"]


SAMPLE_ALL_AUGMENTED = """
__all__ = ["func_a"]
__all__ += ["func_b", "func_c"]

def func_a():
    pass

def func_b():
    pass

def func_c():
    pass
"""


def test_extract_all_augmented():
    """__all__ += [...] appends additional exports."""
    module = inspect_source(SAMPLE_ALL_AUGMENTED, module_name="test_mod")

    assert module.all_exports == ["func_a", "func_b", "func_c"]


SAMPLE_ALL_AUGMENTED_ONLY = """
__all__ += ["extra"]

def extra():
    pass
"""


def test_extract_all_augmented_without_base():
    """__all__ += [...] without a prior __all__ = [...] still works."""
    module = inspect_source(SAMPLE_ALL_AUGMENTED_ONLY, module_name="test_mod")

    assert module.all_exports == ["extra"]


SAMPLE_ALL_MULTIPLE_AUGMENTS = """
__all__ = ["a"]
__all__ += ["b"]
__all__ += ["c"]

def a(): pass
def b(): pass
def c(): pass
"""


def test_extract_all_multiple_augments():
    """Multiple __all__ += [...] statements are all collected."""
    module = inspect_source(SAMPLE_ALL_MULTIPLE_AUGMENTS, module_name="test_mod")

    assert module.all_exports == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Module docstring
# ---------------------------------------------------------------------------

SAMPLE_DOCSTRING = '''"""This is the module docstring."""

x: int = 42
'''


def test_module_docstring():
    module = inspect_source(SAMPLE_DOCSTRING, module_name="test_mod")

    assert module.docstring == "This is the module docstring."


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

SAMPLE_VARIABLES = """
VERSION: str = "1.0.0"
MAX_RETRIES = 3
_internal = True
"""


def test_extract_variables():
    module = inspect_source(SAMPLE_VARIABLES, module_name="test_mod")

    names = [v.name for v in module.variables]
    assert "VERSION" in names
    assert "MAX_RETRIES" in names
    assert "_internal" in names  # Inspector captures all; filtering is renderer's job

    version_var = next(v for v in module.variables if v.name == "VERSION")
    assert version_var.annotation == "str"
    assert version_var.value == "'1.0.0'"


# ---------------------------------------------------------------------------
# is_public_member
# ---------------------------------------------------------------------------


def test_is_public_member():
    assert is_public_member("my_func")
    assert is_public_member("MyClass")
    assert not is_public_member("_private")
    assert not is_public_member("__very_private")

    # Dunder methods
    assert not is_public_member("__init__", is_method=False)
    assert is_public_member("__init__", is_method=True)
    assert is_public_member("__call__", is_method=True)
    assert not is_public_member("__custom_dunder__", is_method=True)


# ---------------------------------------------------------------------------
# Complex signatures
# ---------------------------------------------------------------------------

SAMPLE_COMPLEX_SIG = (
    "def complex(a, b: int, /, c: str = 'x', "
    "*args: int, key: bool = False, **kwargs) -> None:\n"
    '    """A function with all parameter kinds."""\n'
    "    ...\n"
)


def test_complex_signature():
    module = inspect_source(SAMPLE_COMPLEX_SIG, module_name="test_mod")

    func = module.functions[0]
    params = func.parameters

    # a: positional-only
    assert params[0].name == "a"
    assert params[0].kind == "POSITIONAL_ONLY"

    # b: positional-only
    assert params[1].name == "b"
    assert params[1].kind == "POSITIONAL_ONLY"
    assert params[1].annotation == "int"

    # c: positional-or-keyword with default
    assert params[2].name == "c"
    assert params[2].kind == "POSITIONAL_OR_KEYWORD"
    assert params[2].default == "'x'"

    # *args
    assert params[3].name == "*args"
    assert params[3].kind == "VAR_POSITIONAL"
    assert params[3].annotation == "int"

    # key: keyword-only
    assert params[4].name == "key"
    assert params[4].kind == "KEYWORD_ONLY"

    # **kwargs
    assert params[5].name == "**kwargs"
    assert params[5].kind == "VAR_KEYWORD"


# ---------------------------------------------------------------------------
# Inner classes
# ---------------------------------------------------------------------------

SAMPLE_INNER = '''
class Outer:
    """Outer class."""

    class Inner:
        """Inner class."""

        def inner_method(self) -> None:
            pass
'''


def test_inner_classes():
    module = inspect_source(SAMPLE_INNER, module_name="test_mod")

    outer = module.classes[0]
    assert outer.name == "Outer"
    assert len(outer.inner_classes) == 1

    inner = outer.inner_classes[0]
    assert inner.name == "Inner"
    assert inner.qualname == "Outer.Inner"
    assert len(inner.methods) == 1
    assert inner.methods[0].qualname == "Outer.Inner.inner_method"


# ---------------------------------------------------------------------------
# Decorated class
# ---------------------------------------------------------------------------

SAMPLE_DECORATED = '''
from dataclasses import dataclass

@dataclass
class Config:
    """Configuration dataclass."""
    host: str = "localhost"
    port: int = 8080
    debug: bool = False
'''


def test_decorated_class():
    module = inspect_source(SAMPLE_DECORATED, module_name="test_mod")

    cls = module.classes[0]
    assert cls.name == "Config"
    assert "dataclass" in cls.decorators
    assert len(cls.class_variables) == 3
