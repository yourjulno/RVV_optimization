# CPU-профиль x265: Base и Patched

## Методика

- Нативная ARM64 QEMU 11.1.50 (O2, debug symbols) в Docker Desktop на Apple M4 Pro.
- Foreman QCIF, 32 кадра; VLEN=128, ELEN=64; medium, CRF 28, один поток x265, RVV.
- `perf record -e cpu-clock:u -F 99 -g`: пользовательский CPU, 99 Гц, стеки через frame pointers; CAP_PERFMON.
- Пять пар Base/Patched в порядке AB/BA/AB/BA/AB; без плагинов, perfmap и jitdump.
- Self — средняя по пяти запускам доля сэмплов непосредственно в функции; неизвестные кадры включены в знаменатель.

## Наиболее затратные функции

| Функция | Base Self, % | Patched Self, % |
|---|---:|---:|
| `interval_tree_subtree_search` | 10.76 | 12.63 |
| `helper_lookup_tb_ptr` | 6.70 | 8.06 |
| `riscv_get_tb_cpu_state` | 5.11 | 5.98 |
| `do_vext_vv` | 5.51 | 5.63 |
| `helper_vle8_v` | 4.26 | 4.50 |
| `do_vext_vx` | 4.10 | 3.56 |
| `helper_vsetvl` | 3.41 | 2.21 |
| `helper_vzext_vf2_h` | 1.67 | 2.74 |
| `probe_access` | 0.00 | 2.39 |
| `probe_access_flags` | 2.35 | 0.00 |
| `probe_pages` | 2.04 | 0.00 |
| `qht_lookup_custom` | 2.01 | 1.63 |

## Стек вызовов `vle8.v`

Фрагменты сохранённых стеков, от вызывающей функции к месту сэмпла; адреса и смещения опущены.

**Base**

```text
cpu_loop
└─ cpu_exec
   └─ cpu_exec_setjmp.isra.0
      └─ cpu_exec_loop.isra.0
         └─ cpu_tb_exec
            └─ [unknown] (/tmp/perf-19.map)
               └─ helper_vle8_v
                  └─ probe_pages
                     └─ probe_access_flags
                        └─ page_get_flags
                           └─ interval_tree_subtree_search
```

**Patched**

```text
cpu_loop
└─ cpu_exec
   └─ cpu_exec_setjmp.isra.0
      └─ cpu_exec_loop.isra.0
         └─ cpu_tb_exec
            └─ [unknown] (/tmp/perf-33.map)
               └─ helper_vle8_v
                  └─ probe_access
                     └─ page_get_flags
                        └─ interval_tree_subtree_search
```
