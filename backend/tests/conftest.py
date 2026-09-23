def pytest_addoption(parser):
    parser.addoption("--require-app", action="store_true", help="Fail pending calculation acceptance tests")
