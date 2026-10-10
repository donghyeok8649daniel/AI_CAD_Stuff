# 2.24.2 · Windows file argument compatibility

Fixed startup argument handling that could leave no window visible after selecting PromptCADStudio.exe directly in Windows and double-clicking a `.pcad` file. Previously, the app rejected a file path supplied without `--open`. The Windows file argument and the existing `--open` form now use the same project-opening path. Paths containing Korean characters and spaces are supported. Duplicate project arguments and unknown options remain errors.

```text
PromptCADStudio.exe "C:\Design files\assembly.pcad"
PromptCADStudio.exe --open "C:\Design files\assembly.pcad"
```

File registration now checks and preserves both `UserChoice` and the newer Windows `UserChoiceLatest` key. It does not edit protected choices or their hashes. Ordinary `.json` defaults and the filename-filtered context action for legacy `.cad.json` retain their existing behavior. [Windows association guide in Korean](FILE_ASSOCIATIONS_KO.md).

The 43 affected source tests passed. The rebuilt Windows EXE opened a real project window and tube component when given only a path containing Korean characters and spaces, and exited normally. All 210 bundled CAD modules and the entry point match the verified source. Registry values and association queries alone do not establish that double-click opening works.
