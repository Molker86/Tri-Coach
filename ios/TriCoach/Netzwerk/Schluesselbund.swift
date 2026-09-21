import Foundation
import Security

/// Geheimnisse (HA-Token, Tri-Coach-Sitzung) gehören in den Schlüsselbund,
/// nicht in die UserDefaults.
enum Schluesselbund {
    private static let dienst = "de.molker86.tricoach"

    static func lesen(_ konto: String) -> String? {
        let abfrage: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: dienst,
            kSecAttrAccount as String: konto,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var ergebnis: CFTypeRef?
        guard SecItemCopyMatching(abfrage as CFDictionary, &ergebnis) == errSecSuccess,
              let daten = ergebnis as? Data
        else { return nil }
        return String(data: daten, encoding: .utf8)
    }

    static func schreiben(_ wert: String?, _ konto: String) {
        let basis: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: dienst,
            kSecAttrAccount as String: konto,
        ]
        SecItemDelete(basis as CFDictionary)
        guard let wert, !wert.isEmpty else { return }
        var neu = basis
        neu[kSecValueData as String] = Data(wert.utf8)
        neu[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(neu as CFDictionary, nil)
    }
}
