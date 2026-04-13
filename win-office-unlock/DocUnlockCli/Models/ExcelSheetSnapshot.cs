namespace DocUnlockCli.Models;

public sealed record ExcelSheetSnapshot(string Name, IReadOnlyList<IReadOnlyList<string>> Rows);
