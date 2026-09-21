#if DEBUG
import SwiftUI

#Preview("App") {
    RootView()
        .environment(AppZustand.vorschau())
}

#Preview("Einheit") {
    NavigationStack {
        EinheitDetailView(einheit: Beispieldaten.plan.sessions[1])
    }
    .environment(AppZustand.vorschau())
}

#Preview("Ernährungstag") {
    NavigationStack {
        ErnaehrungsTagView(tag: Beispieldaten.ernaehrung.tage[0])
    }
    .environment(AppZustand.vorschau())
}

#Preview("Einrichtung") {
    NavigationStack {
        EinrichtungView(entwurf: VerbindungsEntwurf())
            .navigationTitle("Tri-Coach")
    }
    .environment(AppZustand())
}
#endif
