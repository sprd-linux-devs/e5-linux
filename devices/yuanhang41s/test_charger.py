"""Execute the profile's real ID and register helpers; no hardware writes."""
from pathlib import Path
import os
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / 'common'
extract = runpy.run_path(str(COMMON / 'test_charger_endpoint.py'))['function']


def execute(code):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root/'test.c').write_text(code)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(root/'test.c'), '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)


@unittest.skipIf(os.name == 'nt', 'Linux C compiler required')
class Charger(unittest.TestCase):
    def test_stock_identity_and_address_ownership(self):
        execute(r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
#define EPROBE_DEFER 517
#define BQ2560X_REG_B 11
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define dev_err_probe(d,e,...) (e)
#define dev_info(...) ((void)0)
#define strscpy(d,s,n) snprintf(d,n,"%s",s)
struct i2c_client { unsigned int addr; void *adapter; };
struct bq2560x_charger_info { struct i2c_client *client;void *dev;char charge_ic_vendor_name[20]; };
static struct i2c_client alternate;
static int first_error,second_error,busy,reads[2],delays,reserves;
static u8 first_id=0x11,second_id;
static void usleep_range(int a,int b){assert(a==5000&&b==5500);delays++;}
static struct i2c_client *devm_i2c_new_dummy_device(void *dev,void *adapter,unsigned int addr){
 (void)dev;assert(addr==0x1a);reserves++;
 if(busy)return (void *)(intptr_t)-EBUSY;
 alternate=(struct i2c_client){addr,adapter};return &alternate;
}
static int bq2560x_read(struct bq2560x_charger_info *info,u8 reg,u8 *value){
 assert(reg==11);unsigned int index=info->client->addr==0x1a;reads[index]++;
 if(index?second_error:first_error)return index?second_error:first_error;
 *value=index?second_id:first_id;return 0;
}
''' + (HERE/'charge-current.h').read_text() +
            (HERE/'charger-variants.h').read_text() +
            (HERE/'charger-identify.c').read_text() + r'''
static void reset(void){first_error=second_error=busy=reads[0]=reads[1]=delays=reserves=0;first_id=0x11;second_id=0;}
int main(void){
 struct i2c_client client={0x6b,0};
 struct bq2560x_charger_info info={.client=&client};
 assert(!yh41s_identify(&info));
 assert(!strcmp(info.charge_ic_vendor_name,"BQ25601")&&info.client==&client&&!reserves&&!delays);
 /* Revision bits do not change PN. Do not import P720S20-only 12/13. */
 for(unsigned int id=0;id<256;id++){
  reset();info.client=&client;first_id=id;
  unsigned int pn=(id>>3)&15;
  int ret=yh41s_identify(&info);
  assert((pn<=2||pn==9)?ret==0:ret==-ENODEV);assert(!reserves);
 }
 for(int n=0;n<3;n++){
  reset();info.client=&client;first_error=n==0?-EIO:n==1?-ENXIO:-EREMOTEIO;
  assert(!yh41s_identify(&info));
  assert(info.client==&alternate&&client.addr==0x6b&&reads[0]==6&&reads[1]==1&&delays==5&&reserves==1);
  assert(!strcmp(info.charge_ic_vendor_name,"SGM41513"));
 }
 reset();info.client=&client;first_error=-EPROBE_DEFER;
 assert(yh41s_identify(&info)==-EPROBE_DEFER&&!reserves&&!delays);
 reset();first_error=-EIO;busy=1;
 assert(yh41s_identify(&info)==-EBUSY&&info.client==&client&&!reads[1]);
 reset();first_error=-EIO;second_error=-EIO;
 assert(yh41s_identify(&info)==-EIO&&info.client==&client&&reads[1]==6);
 reset();first_error=-EIO;second_id=0xff;
 assert(yh41s_identify(&info)==-ENODEV&&info.client==&client);
 reset();client.addr=0x1a;
 assert(!yh41s_identify(&info)&&!reserves&&reads[1]==1);
 client.addr=0x3b;assert(yh41s_identify(&info)==-ENODEV);
 for(unsigned int ma=0;ma<10000;ma++){
  assert(yh41s_variant_charge_code(0x1a,ma)==yh41s_charge_code(ma));
  assert(yh41s_variant_charge_code(0x6b,ma)==(ma>3000?3000:ma)/60);
  assert(yh41s_linear_term_code(ma)==(ma<=60?0:ma>959?15:(ma-60)/60));
 }
 for(unsigned int code=0;code<256;code++){
  assert(yh41s_variant_charge_ma(0x1a,code)==yh41s_charge_ma(code));
  assert(yh41s_variant_charge_ma(0x6b,code)==(code&63)*60);
 }
}
''')

    def test_prepared_helpers_and_repeated_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'drivers/power/supply/bq2560x-charger.c'
            target.parent.mkdir(parents=True)
            donor = (HERE.parent/'m8/port/drivers/power/supply/bq2560x-charger.c').read_text()
            target.write_text(donor.replace('info,BQ2560X_REG_B', 'info, BQ2560X_REG_B'))
            apply = runpy.run_path(str(HERE/'charger.py'))['apply']
            obsolete = target.parent/'yh41s-charger-variants.h'
            obsolete.write_text('unrecognized local edit')
            before = target.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Unrecognized generated'):
                apply(root)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(obsolete.read_text(), 'unrecognized local edit')
            obsolete.write_bytes((HERE/'charger-variants.h').read_bytes())
            apply(root)
            source = target.read_text()
            self.assertFalse((target.parent/'yh41s-charger-variants.h').exists())
            self.assertIn('yh41s_variant_charge_code', (target.parent/'yh41s-charge-current.h').read_text())
            apply(root)
            self.assertEqual(source, target.read_text())
            probe = source[source.index('static int bq2560x_charger_probe('):]
            self.assertLess(probe.index('yh41s_identify(info)'), probe.index('i2c_set_clientdata'))
            self.assertIn('devm_request_threaded_irq(info->dev, info->client->irq,', probe)
            self.assertIn('enable_irq_wake(info->client->irq);', probe)
            self.assertNotIn('unsigned char val = 0;', probe)
            self.assertIn('unsigned char val = 0;', source[:source.index('static int bq2560x_charger_probe(')])
            execute(r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define BQ2560X_REG_2 2
#define BQ2560X_REG_3 3
#define BQ2560X_REG_ICHG_MASK 63
#define BQ2560X_REG_TERMINAL_CUR_MASK 15
#define BIT(n) (1U<<(n))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
struct i2c_client {unsigned int addr;};
struct bq2560x_charger_info {struct i2c_client *client;};
static u8 regs[14];static int error,ext_writes;
static int bq2560x_read(struct bq2560x_charger_info *i,int reg,u8 *v){(void)i;assert(reg==2);*v=regs[reg];return error;}
static int bq2560x_update_bits(struct bq2560x_charger_info *i,int reg,u8 mask,u8 v){
 (void)i;if(error)return error;assert(reg==2||reg==3||reg==13);if(reg==13)ext_writes++;
 regs[reg]=(regs[reg]&~mask)|(v&mask);return 0;
}
''' + (HERE/'charge-current.h').read_text() +
                (HERE/'charger-variants.h').read_text() +
                '\n'.join(extract(source, name) for name in
                    ('bq2560x_charger_set_current', 'bq2560x_charger_get_current',
                     'bq2560x_charger_set_termina_cur')) + r'''
int main(void){
 assert(yh41s_charger_name(0x11));
 struct i2c_client client={0x6b};struct bq2560x_charger_info info={&client};
 unsigned int value;
 for(unsigned int addr=0;addr<2;addr++){
  client.addr=addr?0x1a:0x6b;
  for(unsigned int ma=0;ma<5000;ma++){
   regs[2]=0xc0;
   assert(!bq2560x_charger_set_current(&info,ma*1000));
   assert(regs[2]==(0xc0|yh41s_variant_charge_code(client.addr,ma)));
   assert(!bq2560x_charger_get_current(&info,&value));
   assert(value==yh41s_variant_charge_ma(client.addr,regs[2])*1000);
  }
  ext_writes=0;
  for(unsigned int ma=0;ma<1600;ma++){
   regs[3]=0xf0;assert(!bq2560x_charger_set_termina_cur(&info,ma));assert((regs[3]&0xf0)==0xf0);
   if(!addr)assert((regs[3]&15)==yh41s_linear_term_code(ma)&&ext_writes==0);
  }
  error=-EIO;assert(bq2560x_charger_set_current(&info,1000000)==-EIO);
  assert(bq2560x_charger_get_current(&info,&value)==-EIO);
  assert(bq2560x_charger_set_termina_cur(&info,130)==-EIO);error=0;
 }
}
''')


if __name__ == '__main__':
    unittest.main()
