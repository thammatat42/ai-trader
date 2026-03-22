import py_compile
try:
    py_compile.compile(r'd:\Trade\xauusd_analyzer.py', doraise=True)
    print('Syntax OK')
except py_compile.PyCompileError as e:
    print(f'Syntax ERROR: {e}')
