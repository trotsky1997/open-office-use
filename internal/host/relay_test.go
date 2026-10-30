package host

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/ifuryst/open-browser-use/internal/wire"
)

func TestRelayRemapsRequestIDs(t *testing.T) {
	hostToExtensionReader, hostToExtensionWriter := net.Pipe()
	defer hostToExtensionReader.Close()
	defer hostToExtensionWriter.Close()
	extensionToHostReader, extensionToHostWriter := net.Pipe()
	defer extensionToHostReader.Close()
	defer extensionToHostWriter.Close()

	socketDir := shortSocketDir(t)
	socketPath := filepath.Join(socketDir, "obu.sock")
	relay := NewRelay(Config{SocketDir: socketDir, SocketPath: socketPath}, extensionToHostReader, hostToExtensionWriter)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	errCh := make(chan error, 1)
	go func() { errCh <- relay.Serve(ctx) }()
	waitForSocket(t, socketPath)

	client, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	if err := wire.WriteJSON(client, map[string]any{
		"jsonrpc": "2.0",
		"id":      7,
		"method":  "getInfo",
	}); err != nil {
		t.Fatal(err)
	}

	var forwarded map[string]any
	if err := wire.ReadJSON(hostToExtensionReader, &forwarded); err != nil {
		t.Fatal(err)
	}
	hostID, ok := forwarded["id"].(string)
	if !ok || hostID == "" || hostID == "7" {
		t.Fatalf("expected remapped host id, got %#v", forwarded["id"])
	}

	if err := wire.WriteJSON(extensionToHostWriter, map[string]any{
		"jsonrpc": "2.0",
		"id":      hostID,
		"result":  map[string]any{"type": "extension"},
	}); err != nil {
		t.Fatal(err)
	}

	var response map[string]any
	if err := wire.ReadJSON(client, &response); err != nil {
		t.Fatal(err)
	}
	if response["id"].(float64) != 7 {
		encoded, _ := json.Marshal(response)
		t.Fatalf("expected original client id, got %s", encoded)
	}

	cancel()
	select {
	case <-errCh:
	case <-time.After(time.Second):
		t.Fatal("relay did not stop")
	}
}

func TestRelayBroadcastsExtensionNotificationsToSDKClients(t *testing.T) {
	hostToExtensionReader, hostToExtensionWriter := net.Pipe()
	defer hostToExtensionReader.Close()
	defer hostToExtensionWriter.Close()
	extensionToHostReader, extensionToHostWriter := net.Pipe()
	defer extensionToHostReader.Close()
	defer extensionToHostWriter.Close()

	socketDir := shortSocketDir(t)
	socketPath := filepath.Join(socketDir, "obu.sock")
	relay := NewRelay(Config{SocketDir: socketDir, SocketPath: socketPath}, extensionToHostReader, hostToExtensionWriter)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	errCh := make(chan error, 1)
	go func() { errCh <- relay.Serve(ctx) }()
	waitForSocket(t, socketPath)

	firstClient, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer firstClient.Close()
	secondClient, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer secondClient.Close()
	waitForClients(t, relay, 2)

	notification := map[string]any{
		"jsonrpc": "2.0",
		"method":  "onDownloadChange",
		"params":  map[string]any{"id": "download-1", "status": "started"},
	}
	if err := wire.WriteJSON(extensionToHostWriter, notification); err != nil {
		t.Fatal(err)
	}

	for index, client := range []net.Conn{firstClient, secondClient} {
		_ = client.SetReadDeadline(time.Now().Add(time.Second))
		var received map[string]any
		if err := wire.ReadJSON(client, &received); err != nil {
			t.Fatalf("client %d did not receive notification: %v", index+1, err)
		}
		if received["method"] != "onDownloadChange" {
			encoded, _ := json.Marshal(received)
			t.Fatalf("client %d received unexpected payload: %s", index+1, encoded)
		}
	}

	cancel()
	select {
	case <-errCh:
	case <-time.After(time.Second):
		t.Fatal("relay did not stop")
	}
}

func TestActiveSocketRecordLifecycle(t *testing.T) {
	socketDir := t.TempDir()
	socketPath := filepath.Join(socketDir, "obu.sock")

	if err := WriteActiveSocketRecord(socketDir, socketPath); err != nil {
		t.Fatal(err)
	}
	record, err := ReadActiveSocketRecord(socketDir)
	if err != nil {
		t.Fatal(err)
	}
	if record.SocketPath != socketPath {
		t.Fatalf("expected socket path %q, got %q", socketPath, record.SocketPath)
	}
	if record.PID != os.Getpid() {
		t.Fatalf("expected pid %d, got %d", os.Getpid(), record.PID)
	}
	if record.StartedAt.IsZero() {
		t.Fatal("expected startedAt to be populated")
	}

	if err := RemoveActiveSocketRecord(socketDir, filepath.Join(socketDir, "other.sock")); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(ActiveSocketRecordPath(socketDir)); err != nil {
		t.Fatal("record should not be removed for a different socket path")
	}

	if err := RemoveActiveSocketRecord(socketDir, socketPath); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(ActiveSocketRecordPath(socketDir)); !os.IsNotExist(err) {
		t.Fatalf("expected active socket record to be removed, got %v", err)
	}
}

func TestDefaultSocketPathUsesUUIDFilename(t *testing.T) {
	socketDir := t.TempDir()
	relay := NewRelay(Config{SocketDir: socketDir}, nil, nil)
	socketPath := relay.SocketPath()
	if filepath.Dir(socketPath) != socketDir {
		t.Fatalf("expected socket path under %q, got %q", socketDir, socketPath)
	}
	matched, err := regexp.MatchString(
		`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.sock$`,
		filepath.Base(socketPath),
	)
	if err != nil {
		t.Fatal(err)
	}
	if !matched {
		t.Fatalf("expected UUID socket filename, got %q", filepath.Base(socketPath))
	}
}

func TestDefaultSocketDirUsesShortUnixPath(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows keeps the socket directory under the user temp directory")
	}
	if DefaultSocketDir != "/tmp/open-browser-use" {
		t.Fatalf("expected short default socket dir, got %q", DefaultSocketDir)
	}
	relay := NewRelay(Config{}, nil, nil)
	socketPath := relay.SocketPath()
	if filepath.Dir(socketPath) != DefaultSocketDir {
		t.Fatalf("expected socket path under %q, got %q", DefaultSocketDir, socketPath)
	}
	if len(socketPath) > 100 {
		t.Fatalf("default socket path is too long for macOS sockaddr_un: %q (%d)", socketPath, len(socketPath))
	}
}

func TestDefaultRelayBindsShortUnixSocket(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix socket bind test")
	}
	relay := NewRelay(Config{}, strings.NewReader(""), nil)
	socketPath := relay.SocketPath()
	if len(socketPath) > 100 {
		t.Fatalf("default socket path is too long for macOS sockaddr_un: %q (%d)", socketPath, len(socketPath))
	}

	err := relay.Serve(context.Background())
	if err != nil {
		t.Fatalf("default relay should bind before stdin EOF cleanup, got %v", err)
	}
}

func TestRelayReportsSocketPathLengthOnBindFailure(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix socket bind test")
	}
	longSocketPath := filepath.Join("/tmp", strings.Repeat("obu-long-socket-name-", 8)+".sock")
	relay := NewRelay(Config{SocketPath: longSocketPath}, strings.NewReader(""), nil)

	err := relay.Serve(context.Background())
	if err == nil {
		t.Fatal("expected long Unix socket path bind failure")
	}
	if errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expected bind failure after parent dir exists, got %v", err)
	}
	message := err.Error()
	if !strings.Contains(message, "path length") || !strings.Contains(message, longSocketPath) {
		t.Fatalf("expected bind error to include socket path and length, got %v", err)
	}
}

func waitForSocket(t *testing.T, path string) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(path); err == nil {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("socket was not created: %s", path)
}

func waitForClients(t *testing.T, relay *Relay, count int) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		relay.mu.Lock()
		got := len(relay.clients)
		relay.mu.Unlock()
		if got >= count {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	relay.mu.Lock()
	got := len(relay.clients)
	relay.mu.Unlock()
	t.Fatalf("relay accepted %d clients, want %d", got, count)
}

func shortSocketDir(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("/tmp", "obu-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = os.RemoveAll(dir)
	})
	return dir
}

func TestRelayDropsLateResponsesAfterClientDisconnect(t *testing.T) {
	hostIn, hostOut := net.Pipe()
	defer hostIn.Close()
	defer hostOut.Close()
	extensionIn, extensionOut := net.Pipe()
	defer extensionIn.Close()
	defer extensionOut.Close()
	socketDir := shortSocketDir(t)
	socketPath := filepath.Join(socketDir, "obu.sock")
	relay := NewRelay(Config{SocketDir: socketDir, SocketPath: socketPath}, extensionIn, hostOut)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = relay.Serve(ctx) }()
	waitForSocket(t, socketPath)
	first, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	second, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	waitForClients(t, relay, 2)
	if err := wire.WriteJSON(first, map[string]any{"jsonrpc": "2.0", "id": 1, "method": "getInfo"}); err != nil {
		t.Fatal(err)
	}
	var request map[string]any
	if err := wire.ReadJSON(hostIn, &request); err != nil {
		t.Fatal(err)
	}
	_ = first.Close()
	waitForClients(t, relay, 1)
	if err := wire.WriteJSON(extensionOut, map[string]any{"jsonrpc": "2.0", "id": request["id"], "result": map[string]any{"secret": "private"}}); err != nil {
		t.Fatal(err)
	}
	if err := wire.WriteJSON(extensionOut, map[string]any{"jsonrpc": "2.0", "method": "onTabUpdated", "params": map[string]any{}}); err != nil {
		t.Fatal(err)
	}
	_ = second.SetReadDeadline(time.Now().Add(time.Second))
	var received map[string]any
	if err := wire.ReadJSON(second, &received); err != nil {
		t.Fatal(err)
	}
	if received["method"] != "onTabUpdated" {
		t.Fatalf("unexpected response delivered to another client: %#v", received)
	}
}

func TestRelayCancellationIsScopedToItsClient(t *testing.T) {
	hostIn, hostOut := net.Pipe()
	defer hostIn.Close()
	defer hostOut.Close()
	extensionIn, extensionOut := net.Pipe()
	defer extensionIn.Close()
	defer extensionOut.Close()
	socketDir := shortSocketDir(t)
	socketPath := filepath.Join(socketDir, "obu.sock")
	relay := NewRelay(Config{SocketDir: socketDir, SocketPath: socketPath}, extensionIn, hostOut)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = relay.Serve(ctx) }()
	waitForSocket(t, socketPath)
	first, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	second, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	waitForClients(t, relay, 2)
	if err := wire.WriteJSON(first, map[string]any{"jsonrpc": "2.0", "id": "first", "method": "executeCdp"}); err != nil {
		t.Fatal(err)
	}
	var forwarded map[string]any
	if err := wire.ReadJSON(hostIn, &forwarded); err != nil {
		t.Fatal(err)
	}
	if err := wire.WriteJSON(second, map[string]any{"jsonrpc": "2.0", "method": "obu.cancel", "params": map[string]any{"id": "first"}}); err != nil {
		t.Fatal(err)
	}
	if err := wire.WriteJSON(first, map[string]any{"jsonrpc": "2.0", "method": "obu.cancel", "params": map[string]any{"id": "first"}}); err != nil {
		t.Fatal(err)
	}
	_ = hostIn.SetReadDeadline(time.Now().Add(time.Second))
	var cancelled map[string]any
	if err := wire.ReadJSON(hostIn, &cancelled); err != nil {
		t.Fatal(err)
	}
	params, ok := cancelled["params"].(map[string]any)
	if !ok || cancelled["method"] != "obu.cancel" || params["id"] != forwarded["id"] {
		t.Fatalf("bad cancellation mapping: %#v", cancelled)
	}
}

func TestRelayScopesDebuggerEventsToSubscribedSessions(t *testing.T) {
	hostIn, hostOut := net.Pipe()
	defer hostIn.Close()
	defer hostOut.Close()
	extensionIn, extensionOut := net.Pipe()
	defer extensionIn.Close()
	defer extensionOut.Close()
	socketDir := shortSocketDir(t)
	socketPath := filepath.Join(socketDir, "obu.sock")
	relay := NewRelay(Config{SocketDir: socketDir, SocketPath: socketPath}, extensionIn, hostOut)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = relay.Serve(ctx) }()
	waitForSocket(t, socketPath)
	first, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	second, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	waitForClients(t, relay, 2)
	for _, item := range []struct {
		conn    net.Conn
		session string
	}{{first, "a"}, {second, "b"}} {
		if err := wire.WriteJSON(item.conn, map[string]any{"jsonrpc": "2.0", "id": 1, "method": "attach", "params": map[string]any{"session_id": item.session}}); err != nil {
			t.Fatal(err)
		}
		var forwarded map[string]any
		if err := wire.ReadJSON(hostIn, &forwarded); err != nil {
			t.Fatal(err)
		}
	}
	if err := wire.WriteJSON(extensionOut, map[string]any{"jsonrpc": "2.0", "method": "onCDPEvent", "session_id": "a", "params": map[string]any{"secret": "only a"}}); err != nil {
		t.Fatal(err)
	}
	_ = first.SetReadDeadline(time.Now().Add(time.Second))
	var received map[string]any
	if err := wire.ReadJSON(first, &received); err != nil {
		t.Fatal(err)
	}
	if received["method"] != "onCDPEvent" {
		t.Fatalf("missing scoped event: %#v", received)
	}
	_ = second.SetReadDeadline(time.Now().Add(50 * time.Millisecond))
	if err := wire.ReadJSON(second, &received); err == nil {
		t.Fatalf("other session received event: %#v", received)
	}
}
