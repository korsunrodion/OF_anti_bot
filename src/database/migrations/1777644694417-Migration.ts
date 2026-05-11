import { MigrationInterface, QueryRunner } from "typeorm";

export class Migration1777644694417 implements MigrationInterface {
    name = 'Migration1777644694417'

    public async up(queryRunner: QueryRunner): Promise<void> {
        await queryRunner.query(`ALTER TABLE "tracking_links_subscriber" ADD "total_chargebacks" integer NOT NULL DEFAULT '0'`);
    }

    public async down(queryRunner: QueryRunner): Promise<void> {
        await queryRunner.query(`ALTER TABLE "tracking_links_subscriber" DROP COLUMN "total_chargebacks"`);
    }

}
