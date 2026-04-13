namespace DocCopyCli.Models;

public sealed record ExcelSheetSnapshot(string Name, IReadOnlyList<IReadOnlyList<string>> Rows);
