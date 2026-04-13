namespace DocCopyCli.Models;

public sealed record WordDocumentSnapshot(IReadOnlyList<WordParagraphSnapshot> Paragraphs);

public sealed record WordParagraphSnapshot(int Alignment, IReadOnlyList<WordRunSnapshot> Runs);

public sealed record WordRunSnapshot(
    string Text,
    bool Bold,
    bool Italic,
    bool Underline,
    string? FontName,
    double FontSize,
    string? ColorHex);
