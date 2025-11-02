-- random_paste_loop.scpt
property interval_seconds : 120
property byte_count : 512

on run
  repeat
    set randhex to do shell script "xxd -p -l " & byte_count & " /dev/urandom | tr -d '\\n'"
    tell application "System Events"
      tell process "Terminal"
        keystroke randhex
        key code 36 -- Return
      end tell
    end tell
    delay interval_seconds
  end repeat
end run

