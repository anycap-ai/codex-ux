import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

func emit(_ object: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [])
    print(String(data: data, encoding: .utf8)!)
}

func attr(_ element: AXUIElement, _ name: String) -> Any? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}

func str(_ value: Any?) -> String {
    if let string = value as? String { return string }
    if let number = value as? NSNumber { return number.stringValue }
    if let url = value as? URL { return url.absoluteString }
    if let values = value as? [Any] { return values.map { str($0) }.joined(separator: " ") }
    return value.map { String(describing: $0) } ?? ""
}

func rect(_ value: Any?) -> CGRect {
    guard let value else { return .zero }
    let cfValue = value as CFTypeRef
    guard CFGetTypeID(cfValue) == AXValueGetTypeID() else { return .zero }
    let axValue = value as! AXValue
    var rect = CGRect.zero
    if AXValueGetType(axValue) == .cgRect {
        AXValueGetValue(axValue, .cgRect, &rect)
    }
    return rect
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    return attr(element, kAXChildrenAttribute as String) as? [AXUIElement] ?? []
}

func firstDescendant(_ element: AXUIElement, depth: Int = 0, matches: (AXUIElement) -> Bool) -> AXUIElement? {
    if depth > 80 { return nil }
    if matches(element) { return element }
    for child in children(element) {
        if let found = firstDescendant(child, depth: depth + 1, matches: matches) {
            return found
        }
    }
    return nil
}

func pressReturn() {
    let source = CGEventSource(stateID: .hidSystemState)
    let down = CGEvent(keyboardEventSource: source, virtualKey: 36, keyDown: true)
    let up = CGEvent(keyboardEventSource: source, virtualKey: 36, keyDown: false)
    down?.post(tap: .cghidEventTap)
    usleep(30_000)
    up?.post(tap: .cghidEventTap)
}

func waitUntil(_ timeout: TimeInterval, condition: () -> Bool) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if condition() { return true }
        usleep(100_000)
    }
    return condition()
}

func focusedElement(_ root: AXUIElement) -> AXUIElement? {
    guard let value = attr(root, kAXFocusedUIElementAttribute as String) else { return nil }
    return value as! AXUIElement
}

func sameFrame(_ lhs: AXUIElement, _ rhs: AXUIElement) -> Bool {
    let a = rect(attr(lhs, "AXFrame"))
    let b = rect(attr(rhs, "AXFrame"))
    return abs(a.origin.x - b.origin.x) < 1
        && abs(a.origin.y - b.origin.y) < 1
        && abs(a.width - b.width) < 1
        && abs(a.height - b.height) < 1
}

func framePayload(_ element: AXUIElement?) -> [String: Any] {
    guard let element else { return [:] }
    let frame = rect(attr(element, "AXFrame"))
    return [
        "x": frame.origin.x,
        "y": frame.origin.y,
        "width": frame.width,
        "height": frame.height,
    ]
}

func codexApp() -> NSRunningApplication? {
    return NSWorkspace.shared.runningApplications.first {
        $0.bundleIdentifier == "com.openai.codex" || $0.localizedName == "Codex"
    }
}

func activateCodex() -> (NSRunningApplication, AXUIElement)? {
    guard let app = codexApp() else { return nil }
    app.activate(options: [])
    usleep(200_000)
    return (app, AXUIElementCreateApplication(app.processIdentifier))
}

func openCodexThread(_ threadID: String, delay: Double = 0.8) {
    if !threadID.isEmpty, let threadURL = URL(string: "codex://threads/\(threadID)") {
        NSWorkspace.shared.open(threadURL)
        usleep(useconds_t(min(max(delay, 0.0), 5.0) * 1_000_000))
    }
}

func findMenuItem(_ root: AXUIElement, title: String) -> AXUIElement? {
    return firstDescendant(root) { element in
        str(attr(element, kAXRoleAttribute as String)) == "AXMenuItem"
            && str(attr(element, kAXTitleAttribute as String)) == title
    }
}

func pressMenuItem(_ root: AXUIElement, title: String) -> AXError {
    guard let item = findMenuItem(root, title: title) else {
        return .noValue
    }
    return AXUIElementPerformAction(item, kAXPressAction as CFString)
}

func findTextField(_ element: AXUIElement) -> AXUIElement? {
	return firstDescendant(element) { candidate in
		str(attr(candidate, kAXRoleAttribute as String)) == "AXTextField"
	}
}

struct BrowserState {
	let addressField: AXUIElement?
	let addressValue: String
	let webAreaMatchesExpectedURL: Bool

	func isAtExpectedURL(_ expectedURL: String) -> Bool {
		return urlsMatch(addressValue, expectedURL) || webAreaMatchesExpectedURL
	}
}

func findAddressField(_ root: AXUIElement) -> AXUIElement? {
	var preferredAddressField: AXUIElement?
	var fallbackAddressField: AXUIElement?
	var webAreaMatchesExpectedURL = false
	collectBrowserElements(
		root,
		expectedURL: "",
		insideAddressGroup: false,
		preferredAddressField: &preferredAddressField,
		fallbackAddressField: &fallbackAddressField,
		webAreaMatchesExpectedURL: &webAreaMatchesExpectedURL
	)
	return preferredAddressField ?? fallbackAddressField
}

func browserState(_ root: AXUIElement, expectedURL: String) -> BrowserState {
	var preferredAddressField: AXUIElement?
	var fallbackAddressField: AXUIElement?
	var webAreaMatchesExpectedURL = false
	collectBrowserElements(
		root,
		expectedURL: expectedURL,
		insideAddressGroup: false,
		preferredAddressField: &preferredAddressField,
		fallbackAddressField: &fallbackAddressField,
		webAreaMatchesExpectedURL: &webAreaMatchesExpectedURL
	)

	let addressField = preferredAddressField ?? fallbackAddressField
	let addressValue = addressField.map { str(attr($0, kAXValueAttribute as String)) } ?? ""
	return BrowserState(
		addressField: addressField,
		addressValue: addressValue,
		webAreaMatchesExpectedURL: webAreaMatchesExpectedURL
	)
}

func collectBrowserElements(
	_ element: AXUIElement,
	expectedURL: String,
	insideAddressGroup: Bool,
	depth: Int = 0,
	preferredAddressField: inout AXUIElement?,
	fallbackAddressField: inout AXUIElement?,
	webAreaMatchesExpectedURL: inout Bool
) {
	if depth > 80 { return }
	if preferredAddressField != nil && (expectedURL.isEmpty || webAreaMatchesExpectedURL) { return }

	let role = str(attr(element, kAXRoleAttribute as String))
	var isInsideAddressGroup = insideAddressGroup
	var classes = ""

	if preferredAddressField == nil || role == "AXTextField" {
		classes = str(attr(element, "AXDOMClassList"))
		isInsideAddressGroup = insideAddressGroup || classes.contains("group/address-bar")
	}

	if role == "AXTextField" {
		if isInsideAddressGroup {
			preferredAddressField = element
		} else if fallbackAddressField == nil {
			if classes.isEmpty {
				classes = str(attr(element, "AXDOMClassList"))
			}
			let frame = rect(attr(element, "AXFrame"))
			if !classes.contains("ProseMirror")
				&& frame.origin.y >= 50
				&& frame.origin.y <= 160
				&& frame.width >= 150
			{
				fallbackAddressField = element
			}
		}
	} else if !expectedURL.isEmpty && !webAreaMatchesExpectedURL && role == "AXWebArea" {
		webAreaMatchesExpectedURL = urlsMatch(str(attr(element, "AXURL")), expectedURL)
	}

	if preferredAddressField != nil && (expectedURL.isEmpty || webAreaMatchesExpectedURL) { return }
	for child in children(element) {
		collectBrowserElements(
			child,
			expectedURL: expectedURL,
			insideAddressGroup: isInsideAddressGroup,
			depth: depth + 1,
			preferredAddressField: &preferredAddressField,
			fallbackAddressField: &fallbackAddressField,
			webAreaMatchesExpectedURL: &webAreaMatchesExpectedURL
		)
		if preferredAddressField != nil && (expectedURL.isEmpty || webAreaMatchesExpectedURL) { return }
	}
}

func isLikelyAddressField(_ element: AXUIElement) -> Bool {
	let role = str(attr(element, kAXRoleAttribute as String))
	if role != "AXTextField" { return false }

	let classes = str(attr(element, "AXDOMClassList"))
	if classes.contains("ProseMirror") { return false }

	let frame = rect(attr(element, "AXFrame"))
	return frame.origin.y >= 50
		&& frame.origin.y <= 160
		&& frame.width >= 150
}

func addressFieldValue(_ element: AXUIElement?) -> String {
	guard let element else { return "" }
	return str(attr(element, kAXValueAttribute as String))
}

func addressFieldStillValid(_ element: AXUIElement?) -> Bool {
	guard let element else { return false }
	return isLikelyAddressField(element)
}

func pageURLMatches(_ root: AXUIElement, expectedURL: String) -> Bool {
	return firstDescendant(root) { element in
		let role = str(attr(element, kAXRoleAttribute as String))
		let url = str(attr(element, "AXURL"))
		return role == "AXWebArea" && urlsMatch(url, expectedURL)
	} != nil
}

func currentAddressValue(_ root: AXUIElement) -> String {
	guard let field = findAddressField(root) else { return "" }
	return addressFieldValue(field)
}

func browserIsAtExpectedURL(_ root: AXUIElement, expectedURL: String) -> Bool {
	let state = browserState(root, expectedURL: expectedURL)
	return state.isAtExpectedURL(expectedURL)
}

func browserIsAtExpectedURL(
	_ root: AXUIElement,
	expectedURL: String,
	addressField: AXUIElement?
) -> Bool {
	let addressValue = addressFieldValue(addressField)
	if urlsMatch(addressValue, expectedURL) {
		return true
	}
	if addressFieldStillValid(addressField) {
		return false
	}
	return pageURLMatches(root, expectedURL: expectedURL)
}

func normalizedURLText(_ value: String) -> String {
	var text = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
	if text.hasPrefix("http://") {
		text.removeFirst("http://".count)
	} else if text.hasPrefix("https://") {
		text.removeFirst("https://".count)
	}
	while text.hasSuffix("/") {
		text.removeLast()
	}
	return text
}

func urlsMatch(_ observed: String, _ expected: String) -> Bool {
	let observedURL = normalizedURLText(observed)
	let expectedURL = normalizedURLText(expected)
	if observedURL.isEmpty || expectedURL.isEmpty { return false }
	return observedURL == expectedURL || observedURL.hasPrefix(expectedURL + "/")
}

func normalizedComposerText(_ value: String) -> String {
	let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
	return text.hasPrefix("Ask for") ? "" : text
}

func walkComposers(
    _ element: AXUIElement,
    depth: Int = 0,
    candidates: inout [(element: AXUIElement, frame: CGRect, value: String, classes: String)]
) {
    if depth > 80 { return }

    let role = str(attr(element, kAXRoleAttribute as String))
    let classes = str(attr(element, "AXDOMClassList"))
    let value = str(attr(element, kAXValueAttribute as String))
    if role == "AXTextArea" && classes.contains("ProseMirror") {
        candidates.append((element, rect(attr(element, "AXFrame")), value, classes))
    }

    for child in children(element) {
        walkComposers(child, depth: depth + 1, candidates: &candidates)
    }
}

func runOpenBrowser() -> Int32 {
    let args = CommandLine.arguments
    guard args.count >= 3, let browserURL = URL(string: args[2]) else {
        emit(["ok": false, "error": "Missing browser URL"])
        return 2
    }
    guard AXIsProcessTrusted() else {
        emit(["ok": false, "error": "Accessibility permission is not trusted"])
        return 3
    }

    let expectedURL = browserURL.absoluteString
    let threadID = args.count >= 4 ? args[3].trimmingCharacters(in: .whitespacesAndNewlines) : ""
    openCodexThread(threadID, delay: 0.5)

    guard let (_, root) = activateCodex() else {
        emit(["ok": false, "error": "Codex is not running"])
        return 4
    }

    let initialState = browserState(root, expectedURL: expectedURL)
    var addressField = initialState.addressField
    if initialState.isAtExpectedURL(expectedURL) {
        emit([
            "ok": true,
            "url": expectedURL,
            "alreadyOpen": true,
            "addressValue": initialState.addressValue,
        ])
        return 0
    }

    if addressField == nil {
        let openResult = pressMenuItem(root, title: "Open Browser Tab")
        if openResult != .success {
            emit(["ok": false, "error": "Could not open Browser tab", "axError": openResult.rawValue])
            return 5
        }
        let opened = waitUntil(3.0) {
            addressField = findAddressField(root)
            return addressField != nil
        }
        if !opened {
            emit(["ok": false, "error": "Browser address field did not appear after opening Browser tab"])
            return 6
        }
    }

    let focusResult = pressMenuItem(root, title: "Focus Browser Address Bar")
    if focusResult != .success {
        emit(["ok": false, "error": "Could not focus Browser address bar", "axError": focusResult.rawValue])
        return 7
    }
    usleep(200_000)

    addressField = findAddressField(root)

    guard let addressField else {
        emit(["ok": false, "error": "Browser address field not found"])
        return 8
    }

    _ = AXUIElementSetAttributeValue(addressField, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    usleep(100_000)

    let focused = focusedElement(root)
    guard let focusedAddressField = focused, sameFrame(focusedAddressField, addressField) else {
        emit([
            "ok": false,
            "error": "Focused element is not the Browser address field",
            "addressFrame": framePayload(addressField),
            "focusedFrame": framePayload(focused),
            "focusedRole": focused.map { str(attr($0, kAXRoleAttribute as String)) } ?? "",
            "focusedClasses": focused.map { str(attr($0, "AXDOMClassList")) } ?? "",
        ])
        return 9
    }

    let beforeValue = addressFieldValue(addressField)
    if urlsMatch(beforeValue, expectedURL) {
        emit([
            "ok": true,
            "url": expectedURL,
            "alreadyOpen": true,
            "addressValue": beforeValue,
            "addressFrame": framePayload(addressField),
        ])
        return 0
    }

    let setResult = AXUIElementSetAttributeValue(addressField, kAXValueAttribute as CFString, expectedURL as CFTypeRef)
    usleep(120_000)
    let afterValue = addressFieldValue(addressField)
    if setResult != .success || !urlsMatch(afterValue, expectedURL) {
        emit([
            "ok": false,
            "error": "Could not set Browser address field value",
            "axError": setResult.rawValue,
            "beforeValue": beforeValue,
            "afterValue": afterValue,
            "addressFrame": framePayload(addressField),
        ])
        return 10
    }

    pressReturn()
    let loaded = waitUntil(3.0) {
        browserIsAtExpectedURL(root, expectedURL: expectedURL, addressField: addressField)
    }
    let finalValue = addressFieldValue(addressField)

    emit([
        "ok": loaded,
        "url": expectedURL,
        "alreadyOpen": false,
        "beforeValue": beforeValue,
        "afterValue": afterValue,
        "finalValue": finalValue,
        "addressFrame": framePayload(addressField),
        "error": loaded ? "" : "Browser did not report the expected URL after navigation",
    ])
    return loaded ? 0 : 11
}

func runSendPrompt() -> Int32 {
    let environment = ProcessInfo.processInfo.environment
    guard let prompt = environment["CODEX_AUTOMATION_PROMPT"], !prompt.isEmpty else {
        emit(["ok": false, "error": "Missing Codex automation prompt"])
        return 2
    }
    guard AXIsProcessTrusted() else {
        emit(["ok": false, "error": "Accessibility permission is not trusted"])
        return 3
    }

    let threadID = environment["CODEX_AUTOMATION_THREAD_ID"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let delay = Double(environment["CODEX_OPEN_DELAY"] ?? "0.8") ?? 0.8
    openCodexThread(threadID, delay: delay)

    guard let (_, root) = activateCodex() else {
        emit(["ok": false, "error": "Codex is not running"])
        return 4
    }

    var composers: [(element: AXUIElement, frame: CGRect, value: String, classes: String)] = []
    walkComposers(root, candidates: &composers)
    guard let composer = composers.max(by: { $0.frame.midY < $1.frame.midY }) else {
        emit(["ok": false, "error": "Could not find a ProseMirror AXTextArea in Codex"])
        return 5
    }

    if !normalizedComposerText(composer.value).isEmpty {
        emit([
            "ok": false,
            "error": "Codex composer is not empty; refusing to overwrite existing input",
            "candidateCount": composers.count,
            "frame": framePayload(composer.element),
        ])
        return 6
    }

    let focusError = AXUIElementSetAttributeValue(composer.element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    if focusError != .success {
        emit(["ok": false, "error": "Could not focus Codex composer", "axError": focusError.rawValue])
        return 7
    }
    usleep(120_000)

    let focused = focusedElement(root)
    guard let focusedComposer = focused, sameFrame(focusedComposer, composer.element) else {
        emit([
            "ok": false,
            "error": "Focused element is not the Codex composer",
            "frame": framePayload(composer.element),
            "focusedFrame": framePayload(focused),
            "focusedRole": focused.map { str(attr($0, kAXRoleAttribute as String)) } ?? "",
            "focusedClasses": focused.map { str(attr($0, "AXDOMClassList")) } ?? "",
        ])
        return 8
    }

    let setError = AXUIElementSetAttributeValue(composer.element, kAXValueAttribute as CFString, prompt as CFTypeRef)
    usleep(120_000)

    let inserted = str(attr(composer.element, kAXValueAttribute as String))
    if setError != .success || inserted != prompt {
        emit([
            "ok": false,
            "error": "Could not set Codex composer value",
            "axError": setError.rawValue,
            "insertedLength": inserted.count,
            "promptLength": prompt.count,
            "frame": framePayload(composer.element),
        ])
        return 9
    }

    pressReturn()
    usleep(120_000)

    emit([
        "ok": true,
        "candidateCount": composers.count,
        "promptLength": prompt.count,
        "frame": framePayload(composer.element),
        "classes": composer.classes,
    ])
    return 0
}

let command = CommandLine.arguments.dropFirst().first ?? ""
switch command {
case "open-browser":
    exit(runOpenBrowser())
case "send-prompt":
    exit(runSendPrompt())
default:
    emit(["ok": false, "error": "Unknown Codex AX automation command: \(command)"])
    exit(1)
}
