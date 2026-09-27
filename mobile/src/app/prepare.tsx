// Model -> printer, material, quality, plate, supports … -> slice (spec sections 3 + 4).
import Ionicons from "@expo/vector-icons/Ionicons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import {
  Banner, Button, Divider, Field, PickerSheet, Row, Screen, Section, Segmented, Stepper, tap, type Choice,
} from "@/components/ui";
import type { JobOptions, ModelFile, Options, Printer, PrinterKind } from "@/lib/api";
import { loadLastPrinter, loadPrefs, saveLastPrinter, savePrefs, useApp } from "@/lib/app";
import { brandOf, comboWarnings, jobName, plateName, shortName } from "@/lib/format";
import { useColors } from "@/lib/theme";

type Params = { link?: string; fileUri?: string; fileName?: string; edit?: string };
type Edit = { printer?: string; file?: string | null; options?: JobOptions; name?: string };
type Sheet = "printer" | "filament" | "process" | "plate" | "file" | null;

export default function Prepare() {
  const { api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const params = useLocalSearchParams<Params>();
  const edit = useMemo<Edit>(() => { try { return params.edit ? JSON.parse(params.edit) : {}; } catch { return {}; } }, [params.edit]);

  const [link, setLink] = useState<string | null>(params.link ?? null);
  const [name, setName] = useState<string>(params.fileName ?? edit.name ?? "");
  const [error, setError] = useState<string>("");
  const [listed, setListed] = useState<{ link: string; files: ModelFile[] } | null>(null);
  const files = listed && listed.link === link ? listed.files : null;  // null while loading
  const [file, setFile] = useState<string | null>(edit.file ?? null);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [kinds, setKinds] = useState<Record<string, PrinterKind | "offline">>({});
  const [printer, setPrinter] = useState<string>("");
  const [opts, setOpts] = useState<Options | null>(null);
  const [filament, setFilament] = useState("");
  const [process, setProcess] = useState("");
  const [plate, setPlate] = useState("");
  const [supports, setSupports] = useState("off");
  const [brim, setBrim] = useState("auto");
  const [infill, setInfill] = useState<number | null>(null);  // null = profile default
  const [walls, setWalls] = useState<number | null>(null);
  const [more, setMore] = useState(false);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [submitting, setSubmitting] = useState(false);
  const firstLoad = useRef(true);

  // 1. file from the phone -> upload to the server first
  useEffect(() => {
    if (!api || !params.fileUri || link) return;
    api.upload(params.fileUri, params.fileName || "model.stl")
      .then(u => { setLink(u.link); setName(u.name); })
      .catch(e => setError(e.message));
  }, [api, params.fileUri, params.fileName, link]);
  const uploading = !!params.fileUri && !link && !error;

  // 2. files of the model (MQ-02)
  useEffect(() => {
    if (!api || !link) return;
    api.files(link).then(fl => {
      setListed({ link, files: fl });
      if (fl.length === 1) setFile(null);
      else if (!edit.file) {
        const threeMf = fl.filter(f => /\.3mf$/i.test(f.name));
        setFile(threeMf.length === 1 ? String(threeMf[0].index) : null);
      }
    }).catch(e => { setListed({ link, files: [] }); setError(e.message); });
  }, [api, link, edit.file]);

  // 3. printers + their state (DV-01)
  useEffect(() => {
    if (!api) return;
    (async () => {
      try {
        const list = await api.printers();
        setPrinters(list);
        const last = edit.printer ?? (await loadLastPrinter());
        setPrinter(list.find(p => p.id === last)?.id ?? list[0]?.id ?? "");
        list.forEach(p => api.status(p.id)
          .then(s => setKinds(k => ({ ...k, [p.id]: s.kind })))
          .catch(() => setKinds(k => ({ ...k, [p.id]: "offline" }))));
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, [api, edit.printer]);

  // 4. presets for the chosen printer, preselected with the last choices (spec 4)
  const applyDefaults = useCallback((o: Options, keepDetails: JobOptions | null) => {
    const d = o.defaults;
    setSupports(keepDetails?.supports ?? d.supports);
    setBrim(keepDetails?.brim ?? d.brim);
    setInfill(keepDetails?.infill ?? null);
    setWalls(keepDetails?.walls ?? null);
  }, []);

  useEffect(() => {
    if (!api || !printer) return;
    let alive = true;
    (async () => {
      try {
        const useEdit = firstLoad.current && edit.options ? edit.options : null;
        const prefs = useEdit ?? (await loadPrefs(printer)) ?? {};
        let o = await api.options(printer);
        const wanted = prefs.process && o.processes.includes(prefs.process) ? prefs.process : o.defaults.process;
        if (wanted !== o.defaults.process) o = await api.options(printer, wanted);
        if (!alive) return;
        setOpts(o);
        setFilament(prefs.filament && o.materials.includes(prefs.filament) ? prefs.filament : o.defaults.filament);
        setProcess(o.defaults.process);
        setPlate(prefs.bed_type && o.plates.includes(prefs.bed_type) ? prefs.bed_type : o.defaults.bed_type);
        applyDefaults(o, useEdit);
        firstLoad.current = false;
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    })();
    return () => { alive = false; };
  }, [api, printer, edit.options, applyDefaults]);

  const changeProcess = async (p: string) => {
    if (!api || !opts || p === process) return;
    setProcess(p);
    try {
      const o = await api.options(printer, p);
      setOpts(prev => (prev ? { ...prev, defaults: o.defaults } : o));
      applyDefaults(o, null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const d = opts?.defaults;
  const warnings = useMemo(() => (filament && plate ? comboWarnings(t, filament, plate) : []), [t, filament, plate]);
  const needsFile = (files?.length ?? 0) > 1 && !file;
  const printerName = printers.find(p => p.id === printer)?.name ?? printer;

  const submit = async () => {
    if (!api || !link || !opts || !d) return;
    if (needsFile) { setError(t("chooseFile")); return; }
    const o: JobOptions = { process, bed_type: plate };
    if (filament !== d.filament) o.filament = filament;
    if (supports !== d.supports) o.supports = supports;
    if (brim !== d.brim) o.brim = brim;
    if (infill != null && infill !== d.infill) o.infill = infill;
    if (walls != null && walls !== d.walls) o.walls = walls;
    setSubmitting(true);
    setError("");
    try {
      await Promise.all([saveLastPrinter(printer), savePrefs(printer, { filament, process, bed_type: plate })]);
      const { job } = await api.createJob(link, printer, file, o);
      router.replace(`/job/${job}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  // ---------- choices for the picker sheets ----------
  const kindLabel = (id: string) => {
    const k = kinds[id];
    return k ? t.table.printerKinds[k] : undefined;
  };
  const choices: Record<Exclude<Sheet, null>, Choice[]> = {
    printer: printers.map(p => ({ value: p.id, label: p.name, sub: kindLabel(p.id) })),
    filament: (opts?.materials ?? []).map(m => ({ value: m, label: shortName(m), group: brandOf(m) })),
    process: (opts?.processes ?? []).map(p => ({ value: p, label: shortName(p) })),
    plate: (opts?.plates ?? []).map(p => ({ value: p, label: plateName(t, p) })),
    file: (files ?? []).map(f => ({ value: String(f.index), label: f.name,
      sub: f.size ? `${(f.size / 1048576).toFixed(1)} MB` : undefined })),
  };
  const sheetValue: Record<Exclude<Sheet, null>, string | null> = { printer, filament, process, plate, file };
  const sheetSet: Record<Exclude<Sheet, null>, (v: string) => void> = {
    printer: setPrinter, filament: setFilament, process: changeProcess, plate: setPlate, file: setFile,
  };
  const sheetTitle: Record<Exclude<Sheet, null>, string> = {
    printer: t("printer"), filament: t("material"), process: t("quality"), plate: t("plate"), file: t("file"),
  };

  const dot = (id: string) => {
    const k = kinds[id];
    const color = !k ? c.sub : k === "offline" || k === "error" ? c.danger : k === "idle" || k === "done" || k === "stopped" ? c.ok : c.warn;
    return <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: color, marginLeft: 8 }} />;
  };

  if (uploading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.bg }}>
        <ActivityIndicator size="large" color={c.accent} />
        <Text style={{ color: c.text, fontSize: 17, marginTop: 16 }}>{t("uploading")}</Text>
        {name ? <Text style={{ color: c.sub, marginTop: 6 }}>{name}</Text> : null}
      </View>
    );
  }

  const ready = !!(link && opts && files && printer);
  return (
    <Screen footer={
      <Button title={t("slice")} icon="layers-outline" onPress={submit} loading={submitting} disabled={!ready || needsFile} />
    }>
      {error ? <Banner kind="error" text={error} /> : null}

      <Section title={t("model")}>
        <Row icon="cube-outline" label={name || jobName(null, link)} sub={link && !link.startsWith("upload:") ? link : undefined} />
        {files === null && link ? (
          <><Divider /><Row label={t("filesLoading")} right={<ActivityIndicator color={c.accent} />} /></>
        ) : files && files.length > 1 ? (
          <><Divider />
            <Row icon="document-outline" label={file ? files.find(f => String(f.index) === file)?.name ?? t("file") : t("filesMany", { n: files.length })}
              onPress={() => setSheet("file")} />
          </>
        ) : files?.length === 1 && !name ? (
          <><Divider /><Row icon="document-outline" label={files[0].name} /></>
        ) : null}
      </Section>

      {printers.length === 0 && !error ? null : (
        <Section title={t("printer")}>
          <Row icon="print-outline" label={printerName || "…"} value={printer ? kindLabel(printer) : undefined}
            right={printer ? dot(printer) : null} onPress={printers.length > 1 ? () => setSheet("printer") : undefined} />
        </Section>
      )}

      {opts && d ? (
        <>
          {warnings.map(w => <Banner key={w} kind="warn" text={w} />)}
          <Section>
            <Row icon="color-fill-outline" label={t("material")} value={shortName(filament)} onPress={() => setSheet("filament")} />
            <Divider />
            <Row icon="speedometer-outline" label={t("quality")} value={shortName(process)} onPress={() => setSheet("process")} />
            <Divider />
            <Row icon="grid-outline" label={t("plate")} value={plateName(t, plate)} onPress={() => setSheet("plate")} />
          </Section>

          <Section>
            <Field label={t("supports")}>
              <Segmented values={opts.supports} value={supports} onChange={setSupports}
                labels={{ off: t("supOff"), normal: t("supNormal"), tree: t("supTree") }} />
            </Field>
          </Section>

          <Pressable onPress={() => { tap(); setMore(m => !m); }} accessibilityRole="button"
            style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 16, marginBottom: 10 }}>
            <Text style={{ color: c.accent, fontSize: 16, flex: 1 }}>{t("more")}</Text>
            <Ionicons name={more ? "chevron-up" : "chevron-down"} size={18} color={c.accent} />
          </Pressable>
          {more ? (
            <Section>
              <Field label={t("brim")}>
                <Segmented values={opts.brims} value={brim} onChange={setBrim}
                  labels={{ auto: t("brimAuto"), off: t("brimOff"), outer: t("brimOuter") }} />
              </Field>
              <Divider />
              <Field label={t("infill")} hint={infill == null || infill === d.infill ? t("standard") : undefined}>
                <Stepper value={infill ?? d.infill ?? 15} min={0} max={100} step={5} onChange={setInfill} format={v => `${v} %`} />
              </Field>
              <Divider />
              <Field label={t("walls")} hint={walls == null || walls === d.walls ? t("standard") : undefined}>
                <Stepper value={walls ?? d.walls ?? 2} min={1} max={10} onChange={setWalls} />
              </Field>
            </Section>
          ) : null}
        </>
      ) : printer ? (
        <ActivityIndicator color={c.accent} style={{ marginTop: 24 }} />
      ) : null}

      {sheet ? (
        <PickerSheet visible title={sheetTitle[sheet]} choices={choices[sheet]} value={sheetValue[sheet]}
          onPick={sheetSet[sheet]} onClose={() => setSheet(null)} searchLabel={t("search")} closeLabel="OK" />
      ) : null}
    </Screen>
  );
}
