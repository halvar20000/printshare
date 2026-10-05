package io.github.halvar20000.bambulan;

// Bambu Lab printers in LAN-only mode, straight from the phone (beginner mode without a bridge). Plain Java so it can be
// tested with a desktop JDK against a real printer; the Expo module (BambuLanModule.kt) only passes calls through.
// Same protocol as the server's printshare/printers/bambu.py (checked on a P1S, FW 01.09.01.00):
//  - certificate on port 8883: CN = serial number, issuer CN "BBL CA"
//  - MQTT over TLS :8883, user "bblp", password = access code; device/<serial>/report and /request
//  - FTPS with implicit TLS :990, same login; the data channel must resume the control channel's TLS session, and the
//    printer never answers the TLS close of the data channel
//  - prints start from a ".gcode.3mf" = the G-code as Metadata/plate_1.gcode (+ md5, slice_info)

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.cert.Certificate;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

public final class BambuCore {
  public static final int MQTT_PORT = 8883;
  public static final int FTPS_PORT = 990;
  public static final String USER = "bblp";

  private BambuCore() {}

  /** The printer's certificate is signed by Bambu's own CA and names the serial, not the IP: accept it as it is. */
  public static SSLContext trustAll() {
    try {
      SSLContext ctx = SSLContext.getInstance("TLS");
      ctx.init(null, new TrustManager[] {new X509TrustManager() {
        public void checkClientTrusted(X509Certificate[] c, String a) {}
        public void checkServerTrusted(X509Certificate[] c, String a) {}
        public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
      }}, null);
      return ctx;
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }

  private static String cn(String dn) {
    Matcher m = Pattern.compile("(?:^|,)\\s*CN=([^,]+)").matcher(dn == null ? "" : dn);
    return m.find() ? m.group(1).trim() : "";
  }

  /** {serial, issuer CN} of the TLS certificate on port 8883, or null when nothing answers there with TLS. */
  public static String[] readCert(String host, int port, int timeoutMs) {
    try (Socket raw = new Socket()) {
      raw.connect(new InetSocketAddress(host, port), timeoutMs);
      raw.setSoTimeout(timeoutMs);
      SSLSocket s = (SSLSocket) trustAll().getSocketFactory().createSocket(raw, host, port, true);
      s.startHandshake();
      Certificate[] chain = s.getSession().getPeerCertificates();
      s.close();
      if (chain.length == 0 || !(chain[0] instanceof X509Certificate)) return null;
      X509Certificate c = (X509Certificate) chain[0];
      return new String[] {cn(c.getSubjectX500Principal().getName()), cn(c.getIssuerX500Principal().getName())};
    } catch (Exception e) {
      return null;
    }
  }

  public static boolean isBambu(String[] cert) {
    return cert != null && (cert[1].contains("BBL") || cert[1].contains("Bambu"));
  }

  /** Bambu printers among `hosts`: {address, serial} each. A closed port answers fast; ~1 s per silent host. */
  public static List<String[]> probe(List<String> hosts, int port, int timeoutMs) {
    List<String[]> found = Collections.synchronizedList(new ArrayList<>());
    ExecutorService pool = Executors.newFixedThreadPool(32);
    for (String h : hosts) {
      pool.execute(() -> {
        try (Socket raw = new Socket()) {
          raw.connect(new InetSocketAddress(h, port), timeoutMs);
        } catch (IOException e) {
          return;
        }
        String[] cert = readCert(h, port, 3000);
        if (isBambu(cert)) found.add(new String[] {h, cert[0]});
      });
    }
    pool.shutdown();
    try {
      pool.awaitTermination(60, TimeUnit.SECONDS);
    } catch (InterruptedException ignored) {
      Thread.currentThread().interrupt();
    }
    return new ArrayList<>(found);
  }

  // ---------- the print file ----------

  /** filament types and colours from the end of an OrcaSlicer G-code ("; filament_type = PLA;PETG"). */
  static String[][] filaments(File gcode) throws IOException {
    long size = gcode.length();
    int n = (int) Math.min(size, 600_000);
    byte[] tail = new byte[n];
    try (RandomAccessFile f = new RandomAccessFile(gcode, "r")) {
      f.seek(size - n);
      f.readFully(tail);
    }
    String text = new String(tail, StandardCharsets.UTF_8);
    String[] types = field(text, "filament_type");
    String[] colours = field(text, "filament_colour");
    if (types.length == 0) types = new String[] {"PLA"};
    return new String[][] {types, colours};
  }

  private static String[] field(String text, String key) {
    Matcher m = Pattern.compile("(?m)^; " + key + " = (.*)$").matcher(text);
    String v = null;
    while (m.find()) v = m.group(1).trim();
    if (v == null || v.isEmpty()) return new String[0];
    String[] parts = v.split(";");
    for (int i = 0; i < parts.length; i++) parts[i] = parts[i].trim().replace("\"", "");
    return parts;
  }

  private static String xml(String s) {
    return s.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;");
  }

  /** Wraps the G-code into a minimal sliced 3MF; returns the number of filaments in it. */
  public static int wrap3mf(File gcode, File out) throws IOException {
    String[][] fil = filaments(gcode);
    MessageDigest md5;
    try {
      md5 = MessageDigest.getInstance("MD5");
    } catch (Exception e) {
      throw new IOException(e);
    }
    StringBuilder slice = new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<config>\n  <plate>\n"
        + "    <metadata key=\"index\" value=\"1\"/>\n");
    for (int i = 0; i < fil[0].length; i++) {
      String colour = i < fil[1].length && fil[1][i].startsWith("#") ? fil[1][i] : "#FFFFFF";
      slice.append("    <filament id=\"").append(i + 1).append("\" type=\"").append(xml(fil[0][i]))
          .append("\" color=\"").append(xml(colour)).append("\" />\n");
    }
    slice.append("  </plate>\n</config>\n");
    try (ZipOutputStream z = new ZipOutputStream(new FileOutputStream(out))) {
      put(z, "[Content_Types].xml", "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Types xmlns=\"http://schemas."
          + "openxmlformats.org/package/2006/content-types\">\n <Default Extension=\"rels\" ContentType=\"application/"
          + "vnd.openxmlformats-package.relationships+xml\"/>\n <Default Extension=\"model\" ContentType=\"application/"
          + "vnd.ms-package.3dmanufacturing-3dmodel+xml\"/>\n <Default Extension=\"gcode\" ContentType=\"text/x.gcode\"/>"
          + "\n</Types>\n");
      put(z, "_rels/.rels", "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Relationships xmlns=\"http://schemas."
          + "openxmlformats.org/package/2006/relationships\">\n <Relationship Target=\"/3D/3dmodel.model\" Id=\"rel-1\" "
          + "Type=\"http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel\"/>\n</Relationships>\n");
      put(z, "3D/3dmodel.model", "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<model unit=\"millimeter\" xml:lang="
          + "\"en-US\" xmlns=\"http://schemas.microsoft.com/3dmanufacturing/core/2015/02\">\n <metadata name="
          + "\"Application\">PocketPrint3D</metadata>\n <resources/>\n <build/>\n</model>\n");
      put(z, "Metadata/slice_info.config", slice.toString());
      z.putNextEntry(new ZipEntry("Metadata/plate_1.gcode"));
      byte[] buf = new byte[65536];
      try (InputStream in = new FileInputStream(gcode)) {
        int r;
        while ((r = in.read(buf)) > 0) {
          z.write(buf, 0, r);
          md5.update(buf, 0, r);
        }
      }
      z.closeEntry();
      StringBuilder hex = new StringBuilder();
      for (byte b : md5.digest()) hex.append(String.format("%02X", b));
      put(z, "Metadata/plate_1.gcode.md5", hex.toString());
    }
    return fil[0].length;
  }

  private static void put(ZipOutputStream z, String name, String content) throws IOException {
    z.putNextEntry(new ZipEntry(name));
    z.write(content.getBytes(StandardCharsets.UTF_8));
    z.closeEntry();
  }

  // ---------- FTPS upload ----------

  public interface Progress {
    void sent(long bytes);
  }

  private static String reply(BufferedReader in) throws IOException {
    String line = in.readLine();
    if (line == null) throw new IOException("the printer closed the connection");
    if (line.length() > 3 && line.charAt(3) == '-') {          // multi-line reply: up to "<code> "
      String code = line.substring(0, 3) + " ";
      String next;
      while ((next = in.readLine()) != null && !next.startsWith(code)) { /* skip */ }
      if (next != null) line = next;
    }
    return line;
  }

  private static String cmd(OutputStream out, BufferedReader in, String command, String expect) throws IOException {
    out.write((command + "\r\n").getBytes(StandardCharsets.UTF_8));
    out.flush();
    String r = reply(in);
    if (!r.startsWith(expect)) {
      String shown = command.startsWith("PASS") ? "PASS ***" : command;
      throw new IOException(shown + ": " + r);
    }
    return r;
  }

  /** Uploads `file` to the printer's SD card as `remoteName`. */
  public static void upload(String host, String code, File file, String remoteName, Progress progress) throws IOException {
    SSLSocketFactory f = trustAll().getSocketFactory();
    try (Socket rawControl = new Socket()) {
      rawControl.connect(new InetSocketAddress(host, FTPS_PORT), 10_000);
      rawControl.setSoTimeout(30_000);
      SSLSocket control = (SSLSocket) f.createSocket(rawControl, host, FTPS_PORT, true);
      control.startHandshake();
      BufferedReader in = new BufferedReader(new InputStreamReader(control.getInputStream(), StandardCharsets.UTF_8));
      OutputStream out = control.getOutputStream();
      String hello = reply(in);
      if (!hello.startsWith("220")) throw new IOException("FTP: " + hello);
      cmd(out, in, "USER " + USER, "331");
      try {
        cmd(out, in, "PASS " + code, "230");
      } catch (IOException e) {
        throw new IOException("the printer refused the access code");
      }
      cmd(out, in, "PBSZ 0", "200");
      cmd(out, in, "PROT P", "200");
      cmd(out, in, "TYPE I", "200");
      String pasv = cmd(out, in, "PASV", "227");
      Matcher m = Pattern.compile("(\\d+),(\\d+),(\\d+),(\\d+),(\\d+),(\\d+)").matcher(pasv);
      if (!m.find()) throw new IOException("FTP: unexpected PASV answer");
      int port = Integer.parseInt(m.group(5)) * 256 + Integer.parseInt(m.group(6));
      Socket rawData = new Socket();
      rawData.connect(new InetSocketAddress(host, port), 10_000);    // the control host, not the address in PASV
      String started = cmd(out, in, "STOR " + remoteName, "1");
      if (!(started.startsWith("150") || started.startsWith("125"))) throw new IOException("FTP: " + started);
      // host + control port as the session key: the TLS session of the control channel is resumed (the printer
      // refuses a data channel with a fresh session)
      SSLSocket data = (SSLSocket) f.createSocket(rawData, host, FTPS_PORT, true);
      data.setUseClientMode(true);
      data.startHandshake();
      OutputStream dout = data.getOutputStream();
      byte[] buf = new byte[65536];
      long sent = 0;
      try (InputStream src = new FileInputStream(file)) {
        int r;
        while ((r = src.read(buf)) > 0) {
          dout.write(buf, 0, r);
          sent += r;
          if (progress != null) progress.sent(sent);
        }
      }
      dout.flush();
      // no TLS close on the data channel: the printer never answers it - just end the TCP connection
      rawData.close();
      String done = reply(in);
      if (!done.startsWith("226")) throw new IOException("FTP: " + done);
      try {
        out.write("QUIT\r\n".getBytes(StandardCharsets.UTF_8));
        out.flush();
      } catch (IOException ignored) {
        // the upload is done
      }
    }
  }

  static byte[] readAll(InputStream in) throws IOException {
    ByteArrayOutputStream b = new ByteArrayOutputStream();
    byte[] buf = new byte[8192];
    int r;
    while ((r = in.read(buf)) > 0) b.write(buf, 0, r);
    return b.toByteArray();
  }
}
