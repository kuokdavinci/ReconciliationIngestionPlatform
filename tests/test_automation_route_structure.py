import ast
from pathlib import Path


def test_decorated_automation_routes_are_thin_adapters() -> None:
    source_path = Path(__file__).parents[1] / "src/api/automation.py"
    tree = ast.parse(source_path.read_text())
    route_functions = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
            for decorator in node.decorator_list
        ):
            route_functions.append(node)

    assert route_functions
    oversized = {
        node.name: len(node.body)
        for node in route_functions
        if len(node.body) > 12
    }
    assert oversized == {}
