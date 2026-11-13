import EdgeCore
import SwiftUI

enum Fmt {
    static func pct(_ x: Double, digits: Int = 1) -> String {
        String(format: "%.\(digits)f%%", x * 100)
    }

    static func signedPct(_ x: Double) -> String {
        String(format: "%+.1f%%", x * 100)
    }

    static func money(_ x: Double) -> String {
        (x < 0 ? "-$" : "$") + String(format: "%.2f", abs(x))
    }

    static func signedMoney(_ x: Double) -> String {
        (x < 0 ? "-$" : "+$") + String(format: "%.2f", abs(x))
    }

    static func streak(_ n: Int, _ kind: StreakKind = .win) -> String {
        n == 0 ? "—" : "\(n > 0 ? kind.letters.hit : kind.letters.miss)\(abs(n))"
    }
}

/// A headline number with a caption.
struct StatTile: View {
    let title: String
    let value: String
    var detail: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title2.weight(.semibold)).monospacedDigit()
            if let detail { Text(detail).font(.caption).foregroundStyle(.secondary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
    }
}

struct EmptyState: View {
    let title: String
    let message: String
    let icon: String

    var body: some View {
        ContentUnavailableView(title, systemImage: icon, description: Text(message))
    }
}

/// Recent results as a row of squares, oldest first.
struct OutcomeStrip: View {
    let outcomes: [Bool]

    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(outcomes.enumerated()), id: \.offset) { _, hit in
                RoundedRectangle(cornerRadius: 2)
                    .fill(hit ? Color.accentColor : Color.secondary.opacity(0.3))
                    .frame(width: 10, height: 16)
            }
        }
        .accessibilityLabel(outcomes.map { $0 ? "hit" : "miss" }.joined(separator: ", "))
    }
}
