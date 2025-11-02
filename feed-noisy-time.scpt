-- RandomPasteTerminal.scpt
-- Generates 512 random bytes (hex) and sends to the selected Terminal tab every 60s.

property bytes_per_burst : 512
property sleep_seconds : 60

on ensure_terminal_ready()
  tell application "Terminal"
    if (count of windows) = 0 then
      do script "" -- open a window/tab
    end if
    activate
  end tell
end ensure_terminal_ready

on gen_hex(nbytes)
  -- hex avoids control characters; 512 bytes -> 1024 hex chars (single line)
  set cmd to "xxd -p -l " & nbytes & " -c 1024 /dev/urandom | tr -d '\\n'"
  return do shell script cmd
end gen_hex

on run
  ensure_terminal_ready()
  repeat
    set payload to gen_hex(bytes_per_burst)
    tell application "Terminal"
      set t to selected tab of front window
      do script payload in t
    end tell
    delay sleep_seconds
  end repeat
end run

