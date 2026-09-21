import SwiftUI

@main
struct TriCoachApp: App {
    @State private var app = AppZustand()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
        }
    }
}

struct RootView: View {
    @Environment(AppZustand.self) private var app
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let _ = protokolliere("RootView neu gezeichnet: eingerichtet=\(app.istEingerichtet)")
        Group {
            if app.istEingerichtet {
                TabView {
                    KalenderView()
                        .tabItem { Label("Kalender", systemImage: "calendar") }
                    ErnaehrungView()
                        .tabItem { Label("Ernährung", systemImage: "fork.knife") }
                    EinstellungenView()
                        .tabItem { Label("Einstellungen", systemImage: "gearshape") }
                }
                .task { await app.laden() }
            } else {
                NavigationStack {
                    EinrichtungView(entwurf: app.entwurf)
                        .navigationTitle("Tri-Coach")
                }
            }
        }
        #if DEBUG && targetEnvironment(simulator)
        .task {
            Task { await app.automatischAnmelden() }
            await Bildschirmfoto.laufen()
        }
        #endif
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active, app.istEingerichtet else { return }
            Task { await app.ladenFallsVeraltet() }
        }
    }
}
