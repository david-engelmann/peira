# vhs tape for the peira walkthrough. Run with vhs site/assets/gifs/walkthrough.tape
# Uses only the offline mock adapter and the trial-demo fixture. No API keys, no spend.
Output site/assets/gifs/walkthrough.gif
Set Shell "bash"
Set FontSize 18
Set Width 1280
Set Height 720

Type "peira run --adapter mock --suite trial-demo --out /tmp/peira-gif-demo" Enter
Sleep 4s
Type "peira report --run /tmp/peira-gif-demo/mock-trial-demo.json --out /tmp/peira-gif-demo/report.html" Enter
Sleep 2s
