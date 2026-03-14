"""Tests for the code parser (SPEC-03 Section 3)."""

import pytest

from openaustria_rag.ingestion.code_parser import CodeParser, RegexFallbackParser
from openaustria_rag.models import ElementKind


@pytest.fixture
def parser():
    return CodeParser()


JAVA_CODE = """\
package com.example;

/**
 * User service for managing users.
 */
@Service
@Transactional
public class UserService {

    @GetMapping("/users")
    public List<User> getUsers() {
        return userRepo.findAll();
    }

    private void validate(User user) {
        // validation logic
    }
}

public interface UserRepository {
    List<User> findAll();
}
"""

PYTHON_CODE = """\
class UserService:
    \"\"\"Service for managing users.\"\"\"

    def get_users(self):
        \"\"\"Return all users.\"\"\"
        return self.repo.find_all()

    def _validate(self, user):
        pass


def standalone_function():
    pass
"""

TYPESCRIPT_CODE = """\
export class UserController {
    getUsers(): User[] {
        return this.service.getAll();
    }
}

interface UserDTO {
    id: string;
    name: string;
}

function createUser(dto: UserDTO): User {
    return new User(dto);
}
"""


class TestJavaParsing:
    def test_extracts_class(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        classes = [e for e in elements if e.kind == ElementKind.CLASS]
        assert len(classes) == 1
        assert classes[0].short_name == "UserService"

    def test_extracts_methods(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        methods = [e for e in elements if e.kind == ElementKind.METHOD]
        assert len(methods) >= 2
        names = {m.short_name for m in methods}
        assert "getUsers" in names
        assert "validate" in names

    def test_extracts_interface(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        interfaces = [e for e in elements if e.kind == ElementKind.INTERFACE]
        assert len(interfaces) == 1
        assert interfaces[0].short_name == "UserRepository"

    def test_extracts_annotations(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        cls = [e for e in elements if e.kind == ElementKind.CLASS][0]
        assert "@Service" in cls.annotations
        assert "@Transactional" in cls.annotations

    def test_extracts_visibility(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        methods = {m.short_name: m for m in elements if m.kind == ElementKind.METHOD}
        assert methods["getUsers"].visibility == "public"
        assert methods["validate"].visibility == "private"

    def test_method_parent_is_class(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        cls = [e for e in elements if e.kind == ElementKind.CLASS][0]
        methods = [e for e in elements if e.kind == ElementKind.METHOD and e.parent_id == cls.id]
        assert len(methods) >= 2

    def test_qualified_method_name(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        methods = {m.short_name: m for m in elements if m.kind == ElementKind.METHOD}
        assert methods["getUsers"].name == "UserService.getUsers"

    def test_docstring_extracted(self, parser):
        elements = parser.parse(JAVA_CODE, "java", "UserService.java", "doc1")
        cls = [e for e in elements if e.kind == ElementKind.CLASS][0]
        assert cls.docstring is not None
        assert "User service" in cls.docstring


class TestPythonParsing:
    def test_extracts_class(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "service.py", "doc2")
        classes = [e for e in elements if e.kind == ElementKind.CLASS]
        assert len(classes) == 1
        assert classes[0].short_name == "UserService"

    def test_extracts_functions(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "service.py", "doc2")
        funcs = [e for e in elements if e.kind == ElementKind.FUNCTION]
        names = {f.short_name for f in funcs}
        assert "get_users" in names
        assert "standalone_function" in names

    def test_docstring_extracted(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "service.py", "doc2")
        cls = [e for e in elements if e.kind == ElementKind.CLASS][0]
        assert cls.docstring is not None
        assert "Service for managing users" in cls.docstring

    def test_method_docstring(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "service.py", "doc2")
        get_users = [e for e in elements if e.short_name == "get_users"][0]
        assert get_users.docstring is not None
        assert "Return all users" in get_users.docstring

    def test_private_visibility(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "service.py", "doc2")
        validate = [e for e in elements if e.short_name == "_validate"][0]
        assert validate.visibility == "private"

    def test_parent_resolution(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "service.py", "doc2")
        cls = [e for e in elements if e.kind == ElementKind.CLASS][0]
        get_users = [e for e in elements if e.short_name == "get_users"][0]
        assert get_users.parent_id == cls.id
        assert get_users.name == "UserService.get_users"

    def test_standalone_function_no_parent(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "service.py", "doc2")
        standalone = [e for e in elements if e.short_name == "standalone_function"][0]
        assert standalone.parent_id is None


class TestTypeScriptParsing:
    def test_extracts_class(self, parser):
        elements = parser.parse(TYPESCRIPT_CODE, "typescript", "controller.ts", "doc3")
        classes = [e for e in elements if e.kind == ElementKind.CLASS]
        assert len(classes) == 1
        assert classes[0].short_name == "UserController"

    def test_extracts_interface(self, parser):
        elements = parser.parse(TYPESCRIPT_CODE, "typescript", "controller.ts", "doc3")
        interfaces = [e for e in elements if e.kind == ElementKind.INTERFACE]
        assert len(interfaces) == 1
        assert interfaces[0].short_name == "UserDTO"

    def test_extracts_function(self, parser):
        elements = parser.parse(TYPESCRIPT_CODE, "typescript", "controller.ts", "doc3")
        funcs = [e for e in elements if e.kind == ElementKind.FUNCTION]
        assert any(f.short_name == "createUser" for f in funcs)


class TestEdgeCases:
    def test_empty_file(self, parser):
        assert parser.parse("", "python", "empty.py", "doc") == []

    def test_whitespace_only(self, parser):
        assert parser.parse("   \n\n  ", "java", "blank.java", "doc") == []

    def test_comments_only(self, parser):
        elements = parser.parse("# just a comment\n# another one", "python", "c.py", "doc")
        assert elements == []

    def test_line_numbers_correct(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "s.py", "doc")
        cls = [e for e in elements if e.kind == ElementKind.CLASS][0]
        assert cls.start_line == 1
        assert cls.end_line > cls.start_line

    def test_file_path_preserved(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "src/service.py", "doc")
        for e in elements:
            assert e.file_path == "src/service.py"

    def test_document_id_preserved(self, parser):
        elements = parser.parse(PYTHON_CODE, "python", "s.py", "my-doc-id")
        for e in elements:
            assert e.document_id == "my-doc-id"


class TestRegexFallback:
    def test_fallback_on_unknown_language(self, parser):
        code = "class Foo {\n}\nfunction bar() {\n}"
        elements = parser.parse(code, "go", "main.go", "doc")
        names = {e.short_name for e in elements}
        assert "Foo" in names
        assert "bar" in names

    def test_regex_extracts_class(self):
        elements = RegexFallbackParser.parse("class MyClass:", "unknown", "f.x", "d")
        assert len(elements) == 1
        assert elements[0].kind == ElementKind.CLASS
        assert elements[0].short_name == "MyClass"

    def test_regex_extracts_function(self):
        elements = RegexFallbackParser.parse("def my_func():", "unknown", "f.x", "d")
        assert len(elements) == 1
        assert elements[0].kind == ElementKind.FUNCTION

    def test_regex_extracts_interface(self):
        elements = RegexFallbackParser.parse("interface Foo {}", "unknown", "f.x", "d")
        assert len(elements) == 1
        assert elements[0].kind == ElementKind.INTERFACE
